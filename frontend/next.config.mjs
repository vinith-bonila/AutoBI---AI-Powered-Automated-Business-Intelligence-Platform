/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `standalone` emits a self-contained server bundle (node + minimal deps) so
  // the production Docker image is small and needs no `npm install` at runtime.
  output: "standalone",
  // The backend URL is the single piece of deployment configuration the
  // browser needs. It is public by design; secrets never leave the API.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000",
  },
};

export default nextConfig;
