/**
 * Client-side PNG / PDF export of the live dashboard.
 *
 * `html2canvas-pro` is used rather than the original because the app's theme
 * relies on modern CSS colour functions (`oklch`, `color-mix`) that the
 * original html2canvas cannot parse. Both libraries are imported dynamically so
 * they never weigh down the initial dashboard load.
 */

async function renderToCanvas(element: HTMLElement): Promise<HTMLCanvasElement> {
  const { default: html2canvas } = await import("html2canvas-pro");
  // Read the current surface colour so the export matches the active theme.
  const surface =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--color-plane")
      .trim() || "#ffffff";

  return html2canvas(element, {
    backgroundColor: surface,
    scale: Math.min(2, window.devicePixelRatio || 1),
    useCORS: true,
    logging: false,
  });
}

export async function exportDashboardImage(
  element: HTMLElement,
  filename: string,
): Promise<void> {
  const canvas = await renderToCanvas(element);
  const url = canvas.toDataURL("image/png");
  triggerDownload(url, filename);
}

export async function exportDashboardPdf(
  element: HTMLElement,
  filename: string,
): Promise<void> {
  const canvas = await renderToCanvas(element);
  const { jsPDF } = await import("jspdf");

  const imgData = canvas.toDataURL("image/png");
  // Fit the capture onto A4 landscape, splitting across pages when tall.
  const pdf = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();

  const ratio = canvas.width / canvas.height;
  const renderWidth = pageWidth;
  const renderHeight = renderWidth / ratio;

  if (renderHeight <= pageHeight) {
    pdf.addImage(imgData, "PNG", 0, 0, renderWidth, renderHeight);
  } else {
    // Slice the tall image across multiple pages.
    let position = 0;
    let remaining = renderHeight;
    while (remaining > 0) {
      pdf.addImage(imgData, "PNG", 0, position, renderWidth, renderHeight);
      remaining -= pageHeight;
      position -= pageHeight;
      if (remaining > 0) pdf.addPage();
    }
  }

  pdf.save(filename);
}

function triggerDownload(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
