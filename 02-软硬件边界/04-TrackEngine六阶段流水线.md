---
title: 第4章 TrackEngine六阶段流水线
tags: [GNSS, StarTrack, TrackEngine, 数据流]
status: 当前实现
version: V2.0
date: 2026-08-25
cssclasses: [startrack-spec]
---

# 第4章 TrackEngine六阶段流水线

> [!abstract] 本章在全流程中的位置
> 本章把一个PDI从进入软件到生成下一条硬件命令的完整生命史讲清楚。之后所有章节中的同步器、观察器、环路和状态机，都能放回这六个固定阶段理解。

![[../90-附件/图RT-04_总体数据流.svg]]

## 4.1 总入口：`TrackEngine::processPdi()`

软件跟踪核心每收到一条解码后的1 ms PDI，就调用一次 `processPdi()`。即使某个状态的载波观察周期是320 ms，这个函数仍然每毫秒运行，因为它还要：

- 核对上一条命令；
- 推进FLL趋势；
- 更新同步和监测窗口；
- 处理gap和状态pending；
- 生成下一PDI命令。

“日志每20 ms一行”不等于“软件每20 ms才和硬件交互”。日志是降采样输出，PDI服务周期仍是1 ms。

## 4.2 六个阶段总览

| 阶段 | 核心问题 | 主要输出 |
|---:|---|---|
| 1. 确认 | 当前PDI是否连续，上一命令是否生效 | `pdi_ok`、`cmd_ok`、状态提交许可 |
| 2. 解码/选择/擦除 | 当前哪些分量可用于闭环，符号是否已知 | 选中PDI、同步结果、擦除后PDI |
| 3. 形成观察 | 从相关值测得什么 | `FreqObs`、`PhaseObs`、`CodeObs` |
| 4. 更新环路 | 哪些观察可以控制 | 载波频率、码率、`*_used` |
| 5. 更新FSM | 当前策略是否应换档 | candidate、pending、target state |
| 6. 生成命令 | 下一毫秒硬件具体执行什么 | `HwCmd(apply_epoch=E+1)` |

顺序不能随意交换。尤其是“观察形成”和“观察是否使用”必须分开，否则同历元撤销、同步边界和状态门控会发生竞态。

## 4.3 阶段1：确认时间轴和硬件命令

这一阶段检查：

1. epoch是否严格连续；
2. `first_sample`是否接在上一PDI之后；
3. gap、overflow、late等硬件标志是否为false；
4. PDI回报的command id是否等于软件期望；
5. pending状态切换所依赖的命令是否已被确认。

若硬件没有确认新命令，软件不能假设新相位或新步进已经生效。有限码slew的停止也必须等零偏置命令确认，不能只看本地epoch已经到期。

## 4.4 阶段2：选择闭环分量并处理符号

不同信号的闭环分量不同：

- L1 C/A、B1I、G1主要跟踪数据分量；
- L5Q、B2a-P、E5a-Q、E1-C、B1C-P跟踪导频；
- 数据分量即使被记录，也不能偷偷进入pilot-only闭环。

`SignalSync`在此阶段处理bit边界或导频二次码相位。只有符号边界已可靠锁定，`PilotWiper`才会把同一个符号同时乘到该导频分量的所有副本和抽头。

对BOC信号，BOC副本和PRN-only副本必须使用同一个擦除符号，否则ASPeCT公式失去物理意义。

## 4.5 阶段3：观察器各自形成结果

观察器输出不是“一个double”，而是带时标和语义的结构：

- `ready`：观察窗已完成；
- `valid`：统计门通过；
- `physical_valid`：可解释为物理Hz/chip；
- `first_epoch/last_epoch`：使用了哪些PDI；
- `center_s`或等价参考时刻；
- `mode/source_tap/kind`：测量来源与粗细语义。

频率、相位和码观察可以在同一历元分别成熟。它们的窗口也可以不同，例如频率20 ms更新而码观察160 ms更新。

## 4.6 同历元撤销为什么必须存在

BOC预同步时，一个已成熟的频率观察可能先形成，随后同一PDI的码观察确认“当前不是中心”，并启动码slew。此时码率换字会污染刚才的长频率窗口，软件必须在进入环路前撤销本历元 `result.freq`。

所以生产顺序不是“观察器valid就立刻写NCO”，而是：

$$
\text{形成候选观察}
\rightarrow\text{完成同步/码居中边界处理}
\rightarrow\text{决定是否允许使用}.
$$

这也是 `valid` 与 `used` 分开的原因。

## 4.7 阶段4：环路怎样消费观察

载波环每毫秒先 `advanceTo()`，把上次确认的频率和趋势推进到当前时刻。若本历元有合格且被策略允许的频率观察，再 `correct()`。

码环每毫秒都计算载波辅助码率。只有 `CodeObsKind::kFine` 且 `ready&&valid` 的观察才能推进DLL PI状态。BOC粗方向事件不能进入DLL积分器。

因此：

- `freq_valid=true, freq_used=false`可能是正常状态策略门控；
- `code_valid=true, dll_used=false`可能是粗观察或状态边界；
- 不能用“观察没被使用”直接判断观察器有bug。

## 4.8 阶段5：FSM只消费压缩证据

FSM不读取原始相关值，也不重算DFT或鉴别器。它消费的是：

- C/N0控制量及其新鲜度；
- 频率、相位和DLL监测状态；
- 同步是否锁定；
- 当前状态驻留时间；
- 是否有gap、失步或重捕证据；
- 动态趋势是否成熟。

FSM先形成candidate，连续满足后生成pending策略；只有新命令在下一PDI确认，状态才正式commit。第12章会详细解释四阶段提交。

## 4.9 阶段6：生成下一条硬件命令

命令至少包含：

- command id和apply epoch；
- 载波step及可选相位load；
- 码step及可选码相位load；
- 本地信号、分量、副本和抽头配置；
- 当前策略所需的PDI控制位。

普通闭环只更新step，不反复装载相位。相位load会造成离散跳变，只能用于明确的初始化或重捕边界。

## 4.10 `TrackResult`是一张本历元快照

每次 `processPdi()`产生新的 `TrackResult`。其中包含：

- 当前状态和pending状态；
- 频率/相位/码观察；
- 环路输出与是否使用；
- 同步结果；
- C/N0、监测器和只读诊断；
- 下一条硬件命令。

Logger只读取这张快照。若某个字段本历元没有新结果，应明确ready/valid为false，而不是悄悄保留旧值伪装成新鲜结果。需要保持的历史由专门的monitor或display对象携带，并记录age或last_epoch。

## 4.11 一条观察影响硬件的完整路径

以20 ms FLL观察在epoch 500成熟为例：

1. PDI 481到500被观察器积累；
2. `FreqObs`在500形成，带窗口中心参考；
3. 状态策略允许FLL控制，`freq_used=true`；
4. `CarrierLoop`把观察重定时到当前epoch并校正内部频率/趋势；
5. `makeCommand()`生成apply=501的新载波step；
6. PDI 501确认该command id；
7. 软件从501起承认新载波命令已经作用于相关器。

任何一步失败，都应在日志中留下不同证据。调试时应找“第一处因果断点”，而不是只看最后RMS。

## 4.12 锁定边界为什么要清不兼容窗口

导频同步前可能使用平方FLL、五抽头wide FLL或未擦除Prompt。同步并擦除后，观察物理模型发生变化。锁定边界必须：

- 保留当前连续NCO；
- 清除跨边界的观察历史；
- 禁止把锁定前的最后一个wide观察送进锁定后策略；
- 从下一完整窗口重新成熟。

“保留NCO”和“保留观察窗”不是一回事。前者保证控制连续，后者反而可能混入不兼容样本。

## 4.13 对应源码阅读顺序

1. `include/tracking/track_engine.h`：先看持有哪些模块和状态；
2. `src/tracking/track_engine.cpp::processPdi()`：看六阶段顺序；
3. `formObservations()`及各 `form*Obs()`：看观察路由；
4. `updateLoops()`：看 `valid` 如何变成 `used`；
5. `applyPolicy()`、`enterSyncAlignment()`：看边界清窗；
6. `makeCommand()`：看下一PDI命令。

## 4.14 本章检查清单

- 观察器形成结果后是否立刻控制？不是，要经过同历元门控和环路许可。
- FSM是否直接读取原始P/E/L？不读取。
- 状态字段是否在生成pending命令时立即改变？不，等下一PDI确认。
- 锁定边界是否重置NCO？通常不重置，只清不兼容窗口。

---

上一篇：[[03-一毫秒PDI与硬件相关器|第3章 一毫秒PDI与硬件相关器]]　下一篇：[[../03-同步与积分/05-为什么必须先同步再长积分|第5章 为什么必须先同步再长积分]]
