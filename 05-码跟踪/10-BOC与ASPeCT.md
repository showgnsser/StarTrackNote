---
title: 第10章 BOC与ASPeCT：从旁峰牵引到细码跟踪
tags: [GNSS, StarTrack, BOC, ASPeCT, slew, FineCheck]
status: 当前实现
version: V2.0
date: 2026-08-25
cssclasses: [startrack-spec]
---

# 第10章 BOC与ASPeCT：从旁峰牵引到细码跟踪

> [!abstract] 本章在全流程中的位置
> 这是E1/B1C最关键的一章。先解释BOC为什么有旁峰，再推导ASPeCT修改功率和局部鉴别器，最后把 `slew` 与 `FineCheck` 放进完整预同步时序。读完后应知道它们分别在解决什么问题，而不是只记住两个名字。

## 10.1 BOC为什么比BPSK难

BOC在PRN chip内部再乘一个方波子载波。它提高频谱分离和测距性能，但自相关函数不再只有一个平滑主峰，而是带有多个局部峰和零点。

![[../90-附件/图RT-06_BOC双副本.svg]]

如果捕获移交码误差接近$0.35$ chip，原始BOC Prompt可能很小，某个侧抽头反而很强。普通Early-Late可能：

- 给错方向；
- 在旁峰处给出假零点；
- 因Prompt接近0而失去载波观测。

所以E1/B1C不能简单复制BPSK码环。

## 10.2 为什么硬件保留两套副本

每个抽头同时有：

1. BOC副本$R_{BOC}$：真实BOC本地码相关；
2. PRN-only副本$R_{PRN}$：去掉子载波，只保留PRN相关。

两者必须：

- 来自同一PDI；
- 使用同一个载波NCO；
- 使用同一个本地码相位MSB形成BOC符号；
- 同步后擦除同一个导频二次码符号。

否则ASPeCT相减会混入人为相位差。

## 10.3 ASPeCT式(13)：修改相关功率

对任一抽头$t$：

$$
M_t=|R_{BOC,t}|^2-\beta|R_{PRN,t}|^2.
$$

当前固定：

$$
\beta=2.
$$

这不是“两个正功率相加”，而是有符号修改功率。$M_t$可以为负；不能取绝对值，也不能把负值钳为0，因为符号正是旁峰消除的一部分。

同步前，E1/B1C都先在完整主码内部对两副本复数相干，再应用式(13)。跨未知二次码chip只在$M_t$等功率层积累。

## 10.4 ASPeCT式(14)：局部连续码误差

定义BOC分支的复数早晚鉴别量：

$$
D_{BOC}=\Re\left((E_{BOC}-L_{BOC})P_{BOC}^*\right).
$$

PRN-only分支：

$$
D_{PRN}=\Re\left((E_{PRN}-L_{PRN})P_{PRN}^*\right).
$$

ASPeCT内部局部误差：

$$
e_{int}=\frac{D_{BOC}-\beta D_{PRN}}
{(6+\beta d)|P_{BOC}|^2}.
$$

$d$是完整E/L间距。生产 `AspectCodeObserver` 还会把内部输出取负，以统一成StarTrack公共语义“本地码应该如何修正”。

式(14)只在已验证的中央单调域里适合作为连续细误差。它不是任意$\pm0.5$ chip的全局捕获器。

## 10.5 同步前三方向怎样构造

粗牵引不直接使用式(14)连续值，而是先形成五个抽头的式(13)修改功率，再分三组：

$$
G_L=\frac{M_{VE}+M_E}{2},
$$

$$
G_C=M_P,
$$

$$
G_R=\frac{M_L+M_{VL}}{2}.
$$

同侧使用均值而不是max，避免左右各有两个tap、中心只有一个tap造成纯噪声次序偏置。

若最大组为$b$、次大组为$s$，对比度：

$$
\rho=\frac{G_b-G_s}{G_b+G_s+\epsilon}.
$$

只有组值有限、最佳组为正、跨组不近并列、$\rho$过门，才形成一个decision。第一个合格decision只保存方向；第二个独立同向decision才输出`kCoarse`。

## 10.6 什么是 `slew`

![[../90-附件/图RT-03_slew与FineCheck.svg]]

`slew`译为有限码相位斜坡。它不是“把码相位瞬间跳$0.1$ chip”，而是在固定时间内给码率增加一个临时偏置：

$$
R_{slew}=\frac{\Delta c}{T_{slew}}.
$$

例如B1C：

$$
\Delta c=0.1\ \text{chip},
\qquad
T_{slew}=0.160\ \text{s},
$$

$$
R_{slew}=0.625\ \text{chip/s}.
$$

时序规则：

1. 粗方向在epoch $E$确认；
2. slew命令从$E+1$生效；
3. 按绝对epoch持续精确$T_{slew}$；
4. 到期后每条新命令都发送零slew偏置；
5. 只有硬件回报零偏置command id后，才算真正停止；
6. 新粗窗口只能从停止确认后的完整主码重新开始。

gap不能延长slew，也不能让旧stop command id永久粘住。

## 10.7 什么是 `FineCheck`

`FineCheck`译为细码复核。它不是第三条码环，不直接修改NCO。它解决的问题是：

> 粗方向声称已经靠近中心后，当前位置是否真的进入式(14)的中央单调域，并且连续一段时间都稳定？

FineCheck使用稳定抽头几何和ASPeCT式(14)细误差，交给`DllMonitor`统计均值和RMS。只有成熟且两者都小，才打开 `pilot_code_centered`。

| 信号 | FineCheck观察 | 通过门 |
|---|---:|---:|
| E1 | 稳定抽头连续约400 ms | $|mean|\le0.20$ chip且$RMS\le0.20$ chip |
| B1C | 3个160 ms细观察，约480 ms | $|mean|\le0.10$ chip且$RMS\le0.10$ chip |

单个fine invalid只表示证据不足。已经center后，它清监测成熟度但不立即撤销同步；只有硬中断或重新成熟的连续证据明确越界才撤销center。

## 10.8 E1预同步流程

![[../90-附件/图RT-13_E1预同步流程.svg]]

### ShortFast阶段

1. 使用粗抽头$\pm0.25/\pm0.50$ chip；
2. 每个子窗20 ms；
3. 3个子窗形成60 ms decision；
4. 两个独立同向decision，最早120 ms输出；
5. 对比度$\rho\ge0.35$；
6. 非中心输出最多$\pm0.25$ chip有限slew；
7. 粗center只请求切稳定抽头，不能直接开PilotSync。

### LongFast阶段

1. 每个子窗160 ms；
2. 8个子窗形成1.28 s decision；
3. 两个独立decision，最早2.56 s输出；
4. 对比度$\rho\ge0.10$；
5. 仍只发布有限slew。

### FineCheck与同步

切到$\pm0.10/\pm0.20$稳定几何后，等待命令确认，再从完整主码开始FineCheck。通过后冻结预同步载波趋势，下一PDI开放E1 PilotSync；搜索500 ms、独立确认500 ms。

## 10.9 B1C预同步流程

![[../90-附件/图RT-07_B1C预同步流程.svg]]

B1C路径更长：

1. 五抽头10 ms完整主码平方FLL先形成一次有效wide资格；
2. 资格成立同历元清旧Aspect窗口，不消费旧coarse；
3. 160 ms式(13)三方向decision；
4. 两个独立同向decision才输出coarse；
5. 非中心执行$\pm0.1$ chip、160 ms有限slew；
6. stop命令确认后重开wide/Aspect窗口；
7. 若粗decision直接给出center，在清旧窗后立即进入FineCheck；
8. 若持续给出同侧外峰，则第三次同方向slew停止确认后强制请求FineCheck；
9. 3个160 ms式(14)细观察形成约480 ms监测；
10. $|mean|$和RMS都不超过0.10 chip才打开码居中门；
11. PilotSync从下一完整主码开始18 s搜索，再用独立18 s确认。

预同步期间只要尚未锁定，B1C载波继续使用source tap 3五抽头wide FLL；码center只开放PilotSync，不提前降级成Prompt FLL。锁定边界才清wide历史并切同步后路径。

## 10.10 同步后怎样工作

导频已锁定并擦除二次码后：

- 彻底关闭同步前粗包络fallback；
- 使用复相干BOC/PRN-only相关；
- 按式(13)/(14)形成细码误差；
- 输出`CodeObsKind::kFine`进入正常DLL；
- 状态切换只改变观察长度和带宽，不改变beta或公式。

若同步后仍允许粗fallback，噪声侧峰可能再次触发有限slew，破坏已经稳定的主峰。

## 10.11 当前明确没有实现什么

- 不宣称完整CBOC/QMBOC或BOC(6,1)联合接收；
- B1C-D/E1-B不进入pilot-only闭环，只可只读诊断；
- 不使用场景真值选择峰；
- 不按seed、码偏差方向或C/N0切换专用门限；
- 不把E1参数直接复制给B1C；
- 不用绝对值修补式(13)负值。

## 10.12 对应源码

| 功能 | 主要位置 |
|---|---|
| 式(13)/(14) | `src/code_observer/aspect_disc.cpp` |
| 同步后细观察 | `src/code_observer/aspect_code_observer.cpp` |
| 同步前粗观察 | `src/code_observer/aspect_pull_obs.cpp` |
| slew时序 | `src/tracking/track_engine.cpp::startCodeSlew()`等 |
| E1 FineCheck | `updatePilotCenter()`相关函数 |
| B1C FineCheck | `updateB1cPilotCenter()`、`confirmB1cSlew()` |
| BOC双副本硬件 | `src/hardware/hardware_channel.cpp` |

## 10.13 本章小结

ASPeCT用BOC与PRN-only两套相关消除旁峰。式(13)是有符号修改功率，式(14)是中央局部连续误差。粗方向只能产生有绝对结束时间的slew；FineCheck只读地证明已经进入正确主峰；通过后才允许PilotSync。E1和B1C共享物理思想，但几何、时标和同步周期不同。

---

上一篇：[[09-BPSK码环与载波辅助DLL|第9章 BPSK码环与载波辅助DLL]]　下一篇：[[../06-状态机/11-十一状态先分职责再看切换|第11章 十一状态先分职责再看切换]]
