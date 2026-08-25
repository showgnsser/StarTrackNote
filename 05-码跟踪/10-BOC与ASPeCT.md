---
title: 第10章 BOC与ASPeCT：E1/B1C怎样避开旁峰
tags: [GNSS, StarTrack, BOC, ASPeCT, E1, B1C]
status: 当前实现
version: V1.0
date: 2026-08-24
cssclasses: [startrack-spec]
---

# 第10章 BOC与ASPeCT：E1/B1C怎样避开旁峰

> [!abstract] 本章目标
> 解释BOC旁峰为什么会让普通DLL跟错，ASPeCT双副本怎样构造局部唯一峰，以及E1/B1C在同步前怎样用
> 有限码斜坡安全进入局部跟踪域。

> [!note] 先把本章两个专用词讲清楚
> **slew（有限码相位斜坡）**不是直接跳码相位，而是在固定时间内给码率增加临时偏置，
> 积分得到一次有界位移，随后发送零偏置命令并等待硬件PDI确认停止。
> **FineCheck（细码复核）**不是一个新环路，而是粗移动后暂不让DLL PI接管，先用连续
> ASPeCT细码均值和RMS证明Prompt确实进入中央主峰的安全门。完整逐步解释见
> [[../StarTrack跟踪算法完整设计方案|StarTrack跟踪算法完整设计方案]]的第2章术语定义和
> 第10章完整预同步流程。

## 10.1 BOC不是普通BPSK

BOC把PRN码再乘一个方波子载波。优点是频谱分裂、测距斜率更陡；代价是自相关函数有多个峰。

![[90-附件/BPSK与BOC相关峰.svg]]

普通Early-Late只寻找局部零点。在副峰附近也可能有$E\approx L$，所以“DLL误差接近0”不能证明到了主峰。

## 10.2 两个本地副本

StarTrack对E1/B1C同时相关：

1. 完整BOC副本$R_B(\tau)$；
2. 相同PRN码、去掉BOC子载波的PRN-only副本$R_P(\tau)$。

![[../90-附件/图RT-06_BOC双副本.svg]]

两副本必须共享码相位、抽头几何和符号擦除。若一个副本偏半chip，后面的相减没有物理意义。

## 10.3 ASPeCT式(13)：修改功率

每个抽头的修改功率：

$$
R_{mod}(\tau)=|R_B(\tau)|^2-\beta|R_P(\tau)|^2,
$$

当前$\beta=2$。PRN-only项帮助压掉BOC旁峰。

> [!danger] 不能取绝对值
> $R_{mod}$允许为负。若写成$|R_{mod}|$，负旁峰会被翻成正峰，等于重新制造假主峰。

## 10.4 ASPeCT式(14)：局部连续误差

对两副本分别构造Prompt方向点积：

$$
DP_B=\Re\{(E_B-L_B)P_B^*\},
$$

$$
DP_P=\Re\{(E_P-L_P)P_P^*\}.
$$

局部码误差：

$$
\widehat\epsilon_c=
\frac{DP_B-\beta DP_P}
{(6+\beta d)|P_B|^2}.
$$

$d$是完整E-L间距。稳定几何单边0.1 chip时$d=0.2$ chip。输出还按硬件抽头方向转换为
“本地码相对输入信号”的统一符号。

式(14)是主峰附近的连续误差，不是任意$\pm0.5$ chip全域搜索器。

## 10.5 同步前怎样形成宽峰方向

每个完整主码先形成五个抽头的包络或修改功率，再分成三组：

$$
G_L=\frac{G_{VE}+G_E}{2},\qquad G_C=G_P,
\qquad G_R=\frac{G_Late+G_{VL}}{2}.
$$

最佳与次佳对比度：

$$
\rho=\frac{G_{best}-G_{second}}
{|G_{best}|+|G_{second}|}.
$$

同侧两个抽头取平均，避免“两个噪声样本取max”相对单Prompt产生先验偏置。精确并列、近并列、非有限、
最佳组非正或$\rho$不足都拒绝。

## 10.6 有限码斜坡不是跳相位

外峰确认后只发布方向$\pm d_{inner}$，上层在固定$T_s$内叠加码率：

$$
R_{slew}=\frac{\Delta c}{T_s},\qquad
|\Delta c|\le d_{inner}.
$$

![[../90-附件/图RT-03_slew与FineCheck.svg]]

斜坡按绝对历元到期，gap不延长。停止命令未确认前不能开放PilotSync，也不能重复启动新斜坡。

## 10.7 E1预同步流程

E1C闭环，E1B只读。E1流程拆成四段：

![[../90-附件/图RT-13_E1预同步流程.svg]]

当前关键参数：

| 项目 | ShortFast | LongFast |
|---|---:|---:|
| 基础子窗 | 20 ms | 160 ms |
| 每decision子窗 | 3 | 8 |
| 独立decision | 2 | 2 |
| 最早粗方向 | 120 ms | 2560 ms |
| 对比度$\rho$ | 0.35 | 0.10 |
| 粗几何单边 | 0.25/0.50 chip | 0.25/0.50 chip |

稳定几何单边0.1/0.2 chip；细码均值和RMS均不超过0.20 chip才开放同步。码居中后清预同步频率趋势并
冻结NCO，避免PilotSync积累期间参考NCO暗中变化。

## 10.8 B1C预同步流程

B1C-P闭环，B1C-D只读。它的二次码长达18 s，所以载波与码牵引必须在同步前工作：

![[../90-附件/图RT-07_B1C预同步流程.svg]]

关键约束：

1. wide频率资格前，粗码观察只后台积累，不能控制；
2. 粗几何单边0.1/0.2 chip，$\rho=0.10$；
3. 每个decision 160 ms，两个独立同向decision才发布；
4. 每次只slew 0.1 chip；
5. 三次同向slew后从下一个完整主码启动FineCheck；
6. FineCheck均值和RMS均不超过0.10 chip才开放PilotSync；
7. 码center只开放同步，锁定前载波仍用五抽头wide FLL；
8. 锁定边界清wide历史，本PDI不把旧wide频率送入新状态。

## 10.9 同步后的模式

PilotSync锁定并完成二次码擦除后：

- 不再用包络宽峰做持续控制；
- 两副本先按符号统一擦除；
- 可跨完整主码复相干；
- 使用式(14)细码误差进入普通二阶DLL；
- 状态机按统一11状态策略管理载波和码更新周期。

一旦锁定，未擦码PDI不能偷偷退回包络粗判。

## 10.10 什么能力没有实现

当前五抽头和有限slew提供局部吸引与BOC预同步牵引，不是任意码误差的大范围二维重捕获。
尚未实现通用软件时分宽码搜索和运行时回捕获协议。

## 10.11 对应源码

| 功能 | 文件/函数 |
|---|---|
| 式(13)/(14) | `src/code_observer/aspect_disc.cpp` |
| 局部细码 | `src/code_observer/aspect_code_observer.cpp` |
| 宽峰聚合 | `src/code_observer/aspect_pull_obs.cpp` |
| E1/B1C分支 | `TrackEngine::formCodeObs()`、`formB1cCodeObs()` |
| 码居中门 | `updatePilotCenter()`、`updateB1cPilotCenter()` |
| 有限slew | `startCodeSlew()`、`confirmCodeSlew()` |

## 10.12 本章小结

BOC的难点是副峰，不只是噪声。ASPeCT用共享码相位的BOC/PRN-only双副本构造修改功率和局部误差。
同步前只把独立确认的方向变成有限slew；进入主峰并通过连续FineCheck后，才允许导频同步和普通DLL。

---

上一篇：[[09-BPSK码环与载波辅助DLL|BPSK码环与载波辅助DLL]]　下一篇：[[../06-状态机/11-十一状态先分职责再看切换|十一状态先分职责再看切换]]
