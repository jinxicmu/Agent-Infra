# MiniMax-H3 API：首帧必填，末帧可选

完整的客户端接入文档（字段、响应、错误码、幂等重试、Python/curl 示例）：[API_CLIENT_GUIDE.md](API_CLIENT_GUIDE.md)。

Base URL：`https://ai-studio-h3-jvljvcyoaa-uc.a.run.app`

创建：`POST /v2/video_generation`。鉴权：`Authorization: Bearer <client API key>`。建议每个逻辑请求携带唯一 `Idempotency-Key`，网络重试沿用相同 key 和请求内容。

当前使用 “MiniMax H3 - Turbo 4step 768p - Sage 41s” 的源工作流：24 fps、四步采样及原生音频。`resolution` 支持 `480P / 720P / 768P`；`duration` 为 1–15 的整数；`ratio` 支持常用横竖比例、方形和 `adaptive`。三项均可省略，默认 `768P / 5 / 16:9`。档位按像素预算计算，实际宽高对齐到 32 的倍数；完整尺寸表见客户端指南。

## 仅传首帧（I2V）

```json
{
  "model": "MiniMax-H3",
  "mode": "realtime",
  "resolution": "768P",
  "duration": 5,
  "ratio": "16:9",
  "content": [
    {
      "type": "text",
      "text": "景别：过肩镜头/患者看医生\n运镜：切入，稳定构图\n情绪/动作：女医生抬头看向男患者，进入问诊状态。\n台词：女医生：你这些症状从什么时候开始的？\n音效：环境底噪降低，语音清晰\n时长：4s"
    },
    {
      "type": "image_url",
      "role": "first_frame",
      "image_url": "<可直接下载图片的 HTTPS URL>"
    }
  ]
}
```

不需要创建空末帧项、不需要第二次上传，也不需要重复首帧充当末帧。查询结果的 `workflow_type` 为 `i2v_first`，`usage.input_image_count` 为 `1`。

## 首尾帧（FL2V）

在上述 `content` 数组中增加一项，其余参数相同：

```json
{
  "type": "image_url",
  "role": "last_frame",
  "image_url": "<末帧图片的 HTTPS URL>"
}
```

查询结果的 `workflow_type` 为 `fl2v`，`usage.input_image_count` 为 `2`。首尾帧可以使用同一图片 URL；角色必须各出现一次。缺少首帧、重复角色、仅文本请求仍被拒绝。

## 输入地址、时长和结果

API 接收图片下载地址，不接收浏览器登录凭证。`storage.cloud.google.com` 是登录后的存储访问入口，不能直接作为无凭证 worker 的图片地址；私有对象应使用有效期覆盖排队与下载时间的 GCS 签名 GET URL。使用标准 TLS，不能关闭证书校验。带下划线的 bucket 使用 path-style URL，可避免虚拟主机名的证书匹配问题。

提示词原样传递。若要改变时长，修改 `duration`，例如 `4`；提示词中的时长文字不覆盖该字段。帧数向上对齐到 `17k+5`，例如 4 秒请求为 107 帧、约 4.458 秒；5 秒请求为 124 帧、约 5.167 秒。成功结果的 `task.output` 返回实测宽高、fps、帧数和时长。

创建返回 `task_id` 后，轮询 `GET /v2/query/video_generation?task_id=<id>`。成功时 `task.content` 返回私有视频的 `gcs_uri`、`gcs_generation`、`checksum`。访问历史输出需要对应 GCS 读取权限。

发布期间创建接口可能返回 HTTP 503 / `SERVICE_MAINTENANCE`；使用相同幂等键稍后重试。查询、续租和正在执行的任务不依赖新任务准入开关。
