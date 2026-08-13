import type { Metadata } from "next";
import { ExperienceApp } from "./ExperienceApp";

export const metadata: Metadata = {
  title: "BDSM 夏令营",
  description: "从 BDSM Wiki 选择课程，与 AI 一起学习和进行纯文字体验。",
};

export default function Home() {
  return <ExperienceApp />;
}
