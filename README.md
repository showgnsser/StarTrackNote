# StarTrackNote

面向初学者的 StarTrack GNSS 跟踪算法分章节教材。

本仓库按 Obsidian vault 组织，入口是 [`00-首页.md`](00-首页.md)。16章依次覆盖：

1. 跟踪与相关基础；
2. 1 ms PDI和软硬件边界；
3. bit/导频同步与积分；
4. 频率观察、FLL/PLL和载波辅助DLL；
5. BOC、ASPeCT、有限slew与FineCheck；
6. 11状态职责、判据与命令确认；
7. 八种GNSS信号的公共主线和专属分支；
8. C/N0、监测、日志、调试和测试方法。

公式使用Obsidian兼容的MathJax块，所有框架图与时序图均为仓库内静态SVG，不依赖Mermaid或外部链接。内容依据 `/home/showskills/SN770/Project/StarTrack` 当前实现整理，不是捕获算法说明、定点化方案或完整资格报告。
