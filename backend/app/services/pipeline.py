"""The analysis pipeline and its progress tracking.

    CSV -> parse -> profile -> clean -> re-profile -> analyse
        -> KPIs -> charts -> LLM semantics -> spec -> validate -> store

Each stage reports into a `JobState` so the frontend can show real progress
rather than a spinner. The pipeline runs as an asyncio task; a failure at any
stage marks the job failed with a message the UI can render, and never leaves a
half-built dashboard behind.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from ..ai.client import AIService
from ..analysis.eda import run_analysis
from ..analysis.query import DatasetQuery
from ..cleaning.cleaner import clean_dataset
from ..config import Settings
from ..profiling.profiler import profile_dataset
from ..schemas.analysis import AnalysisResult
from ..schemas.api import JobState, PipelineStep
from ..schemas.dashboard import DashboardSpecification
from ..schemas.enums import JobStatus
from ..schemas.profile import DatasetProfile
from ..schemas.quality import DataQualityReport
from ..utils.csvio import CSVParseError, read_csv
from ..utils.logging import get_logger
from .dashboard_builder import build_dashboard
from .storage import StorageBackend

log = get_logger(__name__)

STEPS: tuple[tuple[str, str], ...] = (
    ("upload", "File uploaded"),
    ("parse", "Dataset parsed"),
    ("profile", "Dataset profiled"),
    ("types", "Data types detected"),
    ("quality", "Data quality checked"),
    ("clean", "Data cleaned"),
    ("analyze", "Trends analysed"),
    ("kpi", "KPIs identified"),
    ("dashboard", "Dashboard generated"),
)


class JobTracker:
    """In-memory job registry.

    Kept deliberately simple for the MVP. The interface (`get`, `create`,
    `advance`) is what a Redis or database-backed implementation would expose,
    so swapping it out later is a contained change.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = asyncio.Lock()

    def create(self, dataset_id: str, filename: str) -> JobState:
        now = datetime.now(timezone.utc)
        state = JobState(
            dataset_id=dataset_id,
            filename=filename,
            status=JobStatus.PENDING,
            steps=[PipelineStep(key=key, label=label) for key, label in STEPS],
            created_at=now,
            updated_at=now,
        )
        self._jobs[dataset_id] = state
        return state

    def get(self, dataset_id: str) -> JobState | None:
        return self._jobs.get(dataset_id)

    def start_step(self, dataset_id: str, key: str) -> None:
        state = self._jobs.get(dataset_id)
        if not state:
            return
        state.status = JobStatus.RUNNING
        for step in state.steps:
            if step.key == key:
                step.status = JobStatus.RUNNING
                break
        state.updated_at = datetime.now(timezone.utc)

    def complete_step(
        self, dataset_id: str, key: str, *, detail: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        state = self._jobs.get(dataset_id)
        if not state:
            return
        for step in state.steps:
            if step.key == key:
                step.status = JobStatus.COMPLETE
                step.detail = detail
                step.duration_ms = duration_ms
                break
        done = sum(1 for s in state.steps if s.status == JobStatus.COMPLETE)
        state.progress = round(done / len(state.steps) * 100, 1)
        state.updated_at = datetime.now(timezone.utc)

    def finish(self, dataset_id: str) -> None:
        state = self._jobs.get(dataset_id)
        if not state:
            return
        state.status = JobStatus.COMPLETE
        state.progress = 100.0
        state.updated_at = datetime.now(timezone.utc)

    def fail(self, dataset_id: str, error: str) -> None:
        state = self._jobs.get(dataset_id)
        if not state:
            return
        state.status = JobStatus.FAILED
        state.error = error
        for step in state.steps:
            if step.status == JobStatus.RUNNING:
                step.status = JobStatus.FAILED
        state.updated_at = datetime.now(timezone.utc)

    def remove(self, dataset_id: str) -> None:
        """Forget a job entirely — used when its dataset is deleted."""
        self._jobs.pop(dataset_id, None)

    def prune(self, keep_last: int = 200) -> None:
        if len(self._jobs) <= keep_last:
            return
        ordered = sorted(self._jobs.values(), key=lambda j: j.created_at)
        for state in ordered[: len(self._jobs) - keep_last]:
            self._jobs.pop(state.dataset_id, None)


class PipelineResult:
    def __init__(
        self,
        profile: DatasetProfile,
        quality: DataQualityReport,
        analysis: AnalysisResult,
        specification: DashboardSpecification,
    ):
        self.profile = profile
        self.quality = quality
        self.analysis = analysis
        self.specification = specification


class AnalysisPipeline:
    def __init__(
        self,
        *,
        storage: StorageBackend,
        tracker: JobTracker,
        ai: AIService,
        settings: Settings,
    ):
        self._storage = storage
        self._tracker = tracker
        self._ai = ai
        self._settings = settings

    async def run(self, dataset_id: str, filename: str) -> PipelineResult:
        """Execute the full pipeline for one dataset."""
        tracker, storage, settings = self._tracker, self._storage, self._settings
        started = time.perf_counter()
        query: DatasetQuery | None = None

        try:
            tracker.complete_step(dataset_id, "upload", detail=filename)

            # -- parse ------------------------------------------------------
            tracker.start_step(dataset_id, "parse")
            step_start = time.perf_counter()
            parsed = await asyncio.to_thread(
                read_csv, storage.raw_path(dataset_id), max_rows=settings.max_rows_analyzed
            )
            raw_frame = parsed.frame
            tracker.complete_step(
                dataset_id,
                "parse",
                detail=f"{len(raw_frame):,} rows x {raw_frame.shape[1]} columns",
                duration_ms=_ms(step_start),
            )

            # -- profile ----------------------------------------------------
            tracker.start_step(dataset_id, "profile")
            step_start = time.perf_counter()
            raw_profile = await asyncio.to_thread(
                profile_dataset,
                raw_frame,
                dataset_id=dataset_id,
                name=filename,
                settings=settings,
            )
            tracker.complete_step(
                dataset_id,
                "profile",
                detail=f"Domain detected: {raw_profile.domain_guess}",
                duration_ms=_ms(step_start),
            )

            tracker.start_step(dataset_id, "types")
            type_summary = (
                f"{len(raw_profile.numeric_columns)} numeric, "
                f"{len(raw_profile.categorical_columns)} categorical, "
                f"{len(raw_profile.datetime_columns)} date"
            )
            tracker.complete_step(dataset_id, "types", detail=type_summary)

            tracker.start_step(dataset_id, "quality")
            missing_total = sum(c.missing for c in raw_profile.columns)
            tracker.complete_step(
                dataset_id,
                "quality",
                detail=(
                    f"{raw_profile.n_duplicate_rows:,} duplicate rows, "
                    f"{missing_total:,} missing values"
                ),
            )

            # -- clean ------------------------------------------------------
            tracker.start_step(dataset_id, "clean")
            step_start = time.perf_counter()
            cleaning = await asyncio.to_thread(
                clean_dataset,
                raw_frame,
                raw_profile,
                settings=settings,
                extra_warnings=parsed.warnings,
            )
            clean_frame = cleaning.frame
            quality = cleaning.report

            if clean_frame.empty:
                raise PipelineError(
                    "No rows remained after cleaning, so there is nothing to analyse."
                )

            # Re-profile the cleaned frame: types are now real, and every
            # downstream stage should reason about the data as it will be
            # queried, not as it arrived.
            profile = await asyncio.to_thread(
                profile_dataset,
                clean_frame,
                dataset_id=dataset_id,
                name=filename,
                settings=settings,
            )
            await asyncio.to_thread(storage.save_frame, dataset_id, clean_frame)
            tracker.complete_step(
                dataset_id,
                "clean",
                detail=f"{len(cleaning.report.actions)} cleaning actions applied",
                duration_ms=_ms(step_start),
            )

            # -- analyse ----------------------------------------------------
            tracker.start_step(dataset_id, "analyze")
            step_start = time.perf_counter()
            query = DatasetQuery(clean_frame)
            analysis = await asyncio.to_thread(
                run_analysis, clean_frame, profile, query, settings=settings
            )
            tracker.complete_step(
                dataset_id,
                "analyze",
                detail=(
                    f"{len(analysis.trends)} trends, {len(analysis.segments)} segments, "
                    f"{len(analysis.correlations)} correlations"
                ),
                duration_ms=_ms(step_start),
            )

            # -- KPIs + dashboard -------------------------------------------
            tracker.start_step(dataset_id, "kpi")
            step_start = time.perf_counter()
            specification = await build_dashboard(
                frame=clean_frame,
                profile=profile,
                analysis=analysis,
                quality=quality,
                query=query,
                ai=self._ai,
                settings=settings,
            )
            tracker.complete_step(
                dataset_id,
                "kpi",
                detail=f"{len(specification.kpis)} KPIs selected",
                duration_ms=_ms(step_start),
            )

            tracker.start_step(dataset_id, "dashboard")
            await asyncio.to_thread(storage.save_artifact, dataset_id, "profile", profile)
            await asyncio.to_thread(storage.save_artifact, dataset_id, "quality", quality)
            await asyncio.to_thread(storage.save_artifact, dataset_id, "analysis", analysis)
            await asyncio.to_thread(
                storage.save_artifact, dataset_id, "dashboard", specification
            )
            await asyncio.to_thread(
                storage.save_meta,
                dataset_id,
                {
                    "status": "complete",
                    "n_rows": profile.n_rows,
                    "n_columns": profile.n_columns,
                    "domain": specification.domain,
                    "title": specification.title,
                },
            )
            tracker.complete_step(
                dataset_id,
                "dashboard",
                detail=f"{len(specification.charts)} charts, {len(specification.insights)} insights",
            )
            tracker.finish(dataset_id)

            log.info(
                "Pipeline complete for %s in %.2fs",
                dataset_id, time.perf_counter() - started,
            )
            return PipelineResult(profile, quality, analysis, specification)

        except (CSVParseError, PipelineError) as exc:
            log.warning("Pipeline failed for %s: %s", dataset_id, exc)
            tracker.fail(dataset_id, str(exc))
            await asyncio.to_thread(
                self._storage.save_meta,
                dataset_id,
                {"status": "failed", "error": str(exc)},
            )
            raise
        except Exception as exc:  # unexpected — log the trace, report cleanly
            log.exception("Unexpected pipeline failure for %s", dataset_id)
            message = f"Analysis failed: {exc}"
            tracker.fail(dataset_id, message)
            await asyncio.to_thread(
                self._storage.save_meta,
                dataset_id,
                {"status": "failed", "error": message},
            )
            raise PipelineError(message) from exc
        finally:
            if query is not None:
                query.close()


class PipelineError(RuntimeError):
    """A failure the user should see verbatim."""


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
