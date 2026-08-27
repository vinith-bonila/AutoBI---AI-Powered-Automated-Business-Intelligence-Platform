import { Card } from "@/components/ui";

/** First-load placeholder for the dashboard. */
export function DashboardSkeleton() {
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6" aria-busy="true">
      <div className="skeleton h-8 w-72 rounded" />
      <div className="skeleton mt-2 h-4 w-96 rounded" />

      <div className="mt-6 flex gap-4 border-b border-[var(--color-hairline)] pb-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="skeleton h-5 w-24 rounded" />
        ))}
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="col-span-2">
            <Card className="p-5">
              <div className="skeleton h-3 w-20 rounded" />
              <div className="skeleton mt-4 h-8 w-24 rounded" />
              <div className="skeleton mt-3 h-3 w-28 rounded" />
            </Card>
          </div>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Card className="p-5 lg:col-span-12">
          <div className="skeleton h-4 w-48 rounded" />
          <div className="skeleton mt-4 h-64 w-full rounded" />
        </Card>
        {Array.from({ length: 2 }).map((_, index) => (
          <Card key={index} className="p-5 lg:col-span-6">
            <div className="skeleton h-4 w-40 rounded" />
            <div className="skeleton mt-4 h-64 w-full rounded" />
          </Card>
        ))}
      </div>
    </div>
  );
}
