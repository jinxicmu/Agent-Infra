# H3 FL2V：以 Sage 41s 工作流为准

状态：已部署到 Cloud Run 与运行目录 `Agent-Infra/`。开发分支 `fix/h3-sage41s` 保留在隔离目录 `Agent-Infra-h3-sage41s`。单首帧 I2V 与首尾帧 FL2V 均已通过真实端到端验证，见 [参数更新与验证](H3_PARAMETERS_REPORT.md) 及 [早期输入模式验证](H3_INPUTS_E2E_REPORT.md)。监控工作保持暂停。

## 原始依据

原文件：`/home/kakarot/Documents/zarli_ai/ComfyUI/user/default/workflows/MiniMax H3 - Turbo 4step 768p - Sage 41s.json`。Worker 0 的 UI 工作流副本与它逐字节一致。

仓库保存未经修改的 [源文件](<workflows/source/MiniMax H3 - Turbo 4step 768p - Sage 41s.json>)，SHA-256：`a8fb242c8efb1fdb8ff3485df46dc77d2a9231cfe1e67443933dd59c743219e1`。

执行 `python3 workflows/export_h3.py` 可重新生成 API 图。导出器只支持这个经过审阅的源版本：解析外层暴露参数和子图连接，保留源节点 ID，删除输出不可达的编辑器节点。源文件改变时拒绝直接导出，要求重新检查参数布局。运行时不解析 UI 工作流。

## 发现与修正

| 项目 | 旧 API 适配 | 此次修改 |
|---|---|---|
| 提示词 | 强加 integrated_multimodal_description 包装，追加 soundscape/music N/A | 用户文本逐字传递，保留中文对白、音效、音乐和换行 |
| 输出画布 | 用首帧比例 + 0.98 MP 推导，曾实际输出 1248×832 | 默认保留源 0.98 MP / 16:9 的 1344×768；其他档位和比例按请求计算，32 像素对齐 |
| 输入图 | 每帧额外 nearest-exact 预缩放 | LoadImage 直接连接 H3，由原节点负责缩放 |
| 图与代码关系 | 手工图 + 硬编码节点 + 动态追加缩放节点 | 保存源文件、确定性导出图、显式参数映射，仅绑定任务输入 |
| 图缓存 | 仅按文件名缓存 | 按绝对目录、revision、图文件和映射文件缓存，任务使用独立副本 |
| revision 覆盖 | 图、预设、registry | 额外纳入参数映射、原始 UI 文件和导出器哈希 |

本机 H3 原节点的处理规则是：首帧缩放到目标画布，末帧保持比例覆盖并居中裁剪。此次沿用源节点行为，不额外改变它。输入比例不符时，因此可能出现首帧拉伸或末帧裁剪。

模型与计算主链原先已基本正确：INT8 ConvRot 模型、NVFP4 AWQ 文本编码器、768P Turbo LoRA 强度 1、Euler/simple 四步、video/audio sigma shift 6/3、BasicGuider、视频和音频 VAE 解码，均按源文件保留。LoRA/SigmaShift 节点 ID 恢复为源文件中的 `105:130` / `105:140`。CreateVideo 明确保留 24 fps、8-bit、sRGB 及原生音频。

时长按请求绑定，省略时为 5 秒，不使用子图内部未生效的 2 秒默认值；默认帧数表达式得到 124 帧，24 fps 时约 5.167 秒。请求 seed 仍使用云端分配并持久化的值，不能照搬编辑器 randomize 行为破坏任务恢复。

## API 兼容性

`resolution`、`ratio`、`duration` 现为可配置请求参数，默认 `768P / 16:9 / 5s`。分辨率档位支持 480P、720P、768P；比例支持常用显式比例与 adaptive；时长支持 1–15 的整数。源 selector 的像素预算规则用于计算画布；API 返回实测 output，详见客户端指南。

公开 API 必须包含 first_frame，last_frame 可省略：单首帧归类为 i2v_first，首尾帧归类为 fl2v，使用同一源图与 checkpoint。查询 usage 返回实际输入图片数量。纯文本、仅末帧、重复帧角色仍被拒绝。调用方可省略三项参数使用默认值，也可显式指定受支持的值；主设计与请求示例已同步更新。

源文件的“41s”是其注释记录的历史单次暖机成绩，演示只接首帧，不能直接等同于双帧 API 或两张卡并发的耗时。不承诺 41 秒；实际双 GPU API 测试计时单独记录在验证报告中。

## 验证与发布

- 完整 worker/cloudrun 自动化测试：63 passed（Firestore emulator，未访问生产数据库）。
- 新增验证：源图一致性、外层参数优先、提示词原样传递、直接首尾帧连接、任务间隔离、manifest 哈希覆盖、分辨率档位、常用比例及 adaptive、时长与默认值校验、可选末帧、输入计数与类型、重复/缺失首帧拒绝、发布准入开关。
- 本机 ComfyUI 的原生 validate_prompt 检查候选绑定图，并执行 ResolutionSelector 检查实际画布；只做校验，不载入模型或排队生成任务。具体结果见本目录 `runtime/workflow-validation/`。
- 两种输入均经真实 Cloud Run → Firestore → 独立 GPU worker → ComfyUI → GCS → 客户端查询验证；worker 在空闲时切换代码，ComfyUI 与模型进程未重启。

发布必须协调 Cloud Run、worker 和调用方：先停止新增提交并等旧队列/活动租约处理完，再让两个空闲 worker 停止领取，发布一致的 manifest 与代码，确认调用方参数兼容，启动 worker 后进行真实参数冒烟验证，再恢复正常提交。不能把候选 workflow 文件单独覆盖到运行目录，也不能在旧任务执行途中切换 revision。失败时完整回滚云端和 worker 发布版本；涉及新 revision 的未完成任务必须先显式处理，禁止跨 revision 重放。

当前 workflow revision：`7be6926b7da2552590d82320424a8bd8c76589bd58c51a8412aa18e48052fc29`。
