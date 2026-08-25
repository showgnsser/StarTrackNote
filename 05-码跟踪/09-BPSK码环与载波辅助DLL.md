---
title: 第9章 BPSK码环与载波辅助DLL
tags: [GNSS, StarTrack, DLL, 码环, 载波辅助]
status: 当前实现
version: V2.0
date: 2026-08-25
cssclasses: [startrack-spec]
---

# 第9章 BPSK码环与载波辅助DLL

> [!abstract] 本章在全流程中的位置
> 载波环已经让复相关不再快速旋转。本章解释普通BPSK类信号怎样从Early/Late得到连续码误差、DLL怎样只修“剩余码率”，以及粗方向、细误差和监测结果为何必须使用不同语义。

## 9.1 码环真正控制的是什么

码观察器输出码相位误差，单位chip；码环输出码率修正，单位chip/s；硬件码NCO执行最终码率。

因此DLL不是“把本地码相位直接设为观察值”，而是通过改变码率，让相位误差逐渐回到0：

$$
\frac{d}{dt}\left(\tau_{local}-\tau_{signal}\right)
=R_{local}-R_{signal}.
$$

直接装载码相位会产生离散跳变，只用于明确初始化。正常跟踪通过码率连续修正。

## 9.2 BPSK Early-Late鉴别

常见非相干归一化误差：

$$
e_{EL}=K_d
\frac{|E|^2-|L|^2}
{|E|^2+|L|^2+\epsilon}.
$$

$K_d$把无量纲比值换成chip。实际项目可以使用复数dot形式或五抽头峰策略，但输出必须统一为“本地码修正量”。

正确符号不能凭直觉决定，测试要构造已知 `local - truth` 误差，并证明执行闭环一步后：

$$
|e_{after}|<|e_{before}|.
$$

## 9.3 为什么要选择峰策略

五抽头可能出现：

- Prompt唯一最大；
- Early/Late一侧更强；
- 两侧近并列；
- 全部很弱；
- 某个值NaN或饱和。

码观察器应把这些情况分类，而不是永远给一个误差。普通BPSK局部主峰内可以用P/E/L连续鉴别；大偏差或BOC旁峰需要专门粗牵引，不能扩大普通DLL去承担。

## 9.4 载波辅助码率

载波多普勒与码多普勒来自相同径向速度。若载波多普勒估计为$f_d$：

$$
R_{aid}=f_d\frac{R_c}{f_{carrier}}.
$$

| 符号 | 单位 |
|---|---|
| $f_d$ | Hz |
| $R_c$ | chip/s |
| $f_{carrier}$ | Hz |
| $R_{aid}$ | chip/s |

最终码率：

$$
R_{cmd}=R_c+R_{aid}+R_{DLL}+R_{slew}.
$$

$R_{slew}$只在BOC有限粗牵引期间存在；普通稳定跟踪为0。

## 9.5 DLL的二阶PI状态

对细码误差$e_k$：

$$
I_k=\lambda I_{k-1}+K_i e_k,
$$

$$
R_{DLL,k}=I_k+K_p e_k.
$$

| 项 | 作用 |
|---|---|
| $K_p e_k$ | 立即修正当前相位误差 |
| $I_k$ | 学习长期剩余码率偏差 |
| $\lambda$ | 在极弱或边界状态抑制历史漂移 |

载波辅助已经承担主要动态，所以DLL带宽可以较窄，减少码抖动。

## 9.6 `CodeObsKind`为什么必须区分粗细

StarTrack把码观察分为：

- `kFine`：连续、带chip单位、位于已验证局部单调域，可推进DLL PI；
- `kCoarse`：只表示“应向左/向右移动一次”，不能解释成持续码率误差。

若把$\pm0.1$ chip粗方向直接送进PI，环路会把一次有限相位需求积成长期chip/s偏置。观察缺失时这个偏置还会被零阶保持，导致码相位持续漂移。

因此 `CodeLoop`对coarse观察必须拒绝推进PI。粗方向只由TrackEngine生成有限slew。

## 9.7 什么是DLL缺测保持

稳定细DLL偶尔没有新观察时，保持最近积分状态通常正确，因为真实晶振和动态不会因一次缺测瞬间归零。

但保持只适用于已经建立的细码率残差。预同步粗方向不属于这个状态，必须有明确结束时间。

| 场景 | 正确行为 |
|---|---|
| 稳定`kFine`偶发缺测 | 保持DLL残差，继续载波辅助 |
| `kCoarse`候选未确认 | 不进入控制 |
| 有限slew到期 | 撤销$R_{slew}$，不能等下一观察 |
| gap/cmd mismatch | 按边界合同清监测/PI |

## 9.8 `DllMonitor`不是DLL

DLL每次有细观察就更新控制；`DllMonitor`在更长窗口里统计：

$$
\overline e=\frac{1}{N}\sum_{k=1}^{N}e_k,
$$

$$
e_{rms}=\sqrt{\frac{1}{N}\sum_{k=1}^{N}e_k^2}.
$$

均值小但RMS大，说明误差围绕0剧烈摆动；RMS小但均值大，说明稳定地锁在错误位置。只有两者都小，才是“稳定且居中”。

Monitor输出用于状态机或BOC `FineCheck`，不直接改码率。

## 9.9 状态切换保留什么

码状态换档时通常保留：

- 当前连续码相位；
- 当前码NCO；
- 载波辅助；
- 兼容的DLL积分状态。

清除：

- 与新抽头几何不兼容的观察窗；
- 粗方向候选；
- 未完成slew确认；
- 依赖旧主码分段或旧同步模型的窗口。

不能为了“进入新状态”把码相位装载到0，这会直接破坏连续性。

## 9.10 一个数值例子

假设GPS L1载波多普勒为$+5000$ Hz，载波频率$1.57542\times10^9$ Hz，码率$1.023\times10^6$ chip/s：

$$
R_{aid}=5000\times
\frac{1.023\times10^6}{1.57542\times10^9}
\approx3.247\ \text{chip/s}.
$$

若DLL只需补$-0.05$ chip/s，则最终命令约：

$$
R_{cmd}=1{,}023{,}000+3.247-0.05
=1{,}023{,}003.197\ \text{chip/s}.
$$

如果忘记载波辅助，DLL必须独自估计3.247 chip/s，弱信号长观察下很容易跟不上。

## 9.11 极弱状态为什么限制`code_update_ms`

更长码观察能降噪，但若DLL控制更新超过600 ms，载波辅助未建模的剩余动态可能在两次更新之间积累成大码偏差。因此工程约束是：

$$
\text{code\_update\_ms}\le600.
$$

需要更多能量时，优先使用重叠观察或更长历史统计，而不是把实际码控制更新无限拉长。

## 9.12 对应源码

| 功能 | 主要位置 |
|---|---|
| 码观察公共结构 | `include/model/track_data.h` |
| 普通码观察 | `src/code_observer/code_observer.cpp` |
| 拉入码观察 | `src/code_observer/pull_in_code_obs.cpp` |
| 二阶码环 | `src/code_loop/code_loop.cpp` |
| DLL监测 | `src/monitor/dll_monitor.cpp` |
| 载波辅助和使用门 | `src/tracking/track_engine.cpp::updateCodeLoop()` |

## 9.13 本章小结

DLL控制的是码率而不是直接码相位。最终码率由名义码率、载波辅助、DLL残差和临时slew组成。只有`kFine`连续误差能进入PI；`kCoarse`只允许产生有时限的相位移动。`DllMonitor`负责证明一段时间内均值和RMS都合格，不是第二条码环。

---

上一篇：[[../04-载波跟踪/08-载波环FLL与PLL|第8章 载波环FLL与PLL]]　下一篇：[[10-BOC与ASPeCT|第10章 BOC与ASPeCT]]
