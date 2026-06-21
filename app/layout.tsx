import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Creator Signal",
  description: "Personal creator intelligence hub"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}

