import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: '小苏 · 管理后台', description: '企业内部 AI 助手管理后台' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
