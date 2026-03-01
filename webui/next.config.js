/** @type {import('next').NextConfig} */
const isExport = process.env.NEXT_BUILD_MODE === 'export';

const nextConfig = {
  ...(isExport && {
    output: 'export',
    trailingSlash: true,
  }),
  images: { unoptimized: true },
  ...(!isExport && {
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: 'http://localhost:8000/api/:path*',
        },
      ];
    },
  }),
};
module.exports = nextConfig;
