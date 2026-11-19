import type { NextConfig } from 'next';
const nextConfig: NextConfig = process.env.NEXT_STANDALONE === '1' ? { output: 'standalone' } : {};
export default nextConfig;
