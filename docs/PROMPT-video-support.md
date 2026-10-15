# 任务：参考 xianyu-super-butler 实现闲鱼 IM 视频消息支持

## 背景

我有两个项目：

- **当前项目**（需要修改）：`D:\Myproject\xianyu-auto-reply`
- **参考项目**（只读参考）：`D:\Myproject\xianyu-super-butler`

参考项目支持视频消息的发送和接收。请读取参考项目中的相关实现，然后在当前项目中做相同的改动。

---

## 当前项目的现状

### 消息解析（接收端）

文件：`common/utils/xianyu_message_parser.py` 的 `interpret_content` 函数

目前只处理了以下 contentType：
- `contentType=1`（文本）
- `contentType=2`（图片，取 `image.pics[].url`）
- `contentType=3`（语音，显示为 `[语音消息]`）

视频消息的 contentType 未知，当前代码会打印一行 debug 日志然后返回空，前端最终显示为 `[视频]` 文本标签，视频 URL 被丢弃。

### 消息发送（发送端）

文件：`backend-web/app/services/chat_new/im_client.py`

已有方法：
- `send_text_message`：发送 contentType=1 文本消息
- `send_image_message`：发送 contentType=2 图片消息，图片需先上传到闲鱼 CDN，传入 `image_url`、`width`、`height`

发送图片消息的 IM 协议结构如下（供参考，视频消息结构应类似）：

```python
payload = {
    "contentType": 2,
    "image": {
        "pics": [
            {
                "height": int(height),
                "type": 0,
                "url": image_url,
                "width": int(width),
            }
        ]
    },
}
data_b64 = base64.b64encode(
    json.dumps(payload, ensure_ascii=False).encode("utf-8")
).decode("utf-8")

msg = {
    "lwp": "/r/MessageSend/sendByReceiverScope",
    "headers": {"mid": mid},
    "body": [
        {
            "uuid": message_uuid,
            "cid": full_cid,
            "conversationType": 1,
            "content": {
                "contentType": 101,
                "custom": {"type": 1, "data": data_b64},
            },
            ...
        },
        {"actualReceivers": [full_to, full_self]},
    ],
}
```

### 图片上传

文件：`common/utils/image_uploader.py`（已实现，通过闲鱼 Cookie 上传到 CDN）

### 前端聊天页面

文件：`frontend/src/pages/chat-new/ChatNew.tsx`

- 消息类型 `type` 目前为 `'text' | 'image' | 'system' | 'card'`（定义在 `frontend/src/api/chatNew.ts`）
- 图片消息渲染：`msg.type === 'image'` 时用 `<img src={proxyCdnImageUrl(url)}>` 展示，`proxyCdnImageUrl()` 会把闲鱼 CDN URL 转成后端代理路径 `/api/v1/chat-new/image-proxy?url=...`
- 发送图片：`<input accept="image/*">` 选文件，调用 `sendImageMessage()` API
- 发送图片 API：`POST /api/v1/chat-new/send-image/{account_id}`，multipart form，字段 `cid`、`toUserId`、`image`（文件）
- 图片代理接口（无需认证）：`GET /api/v1/chat-new/image-proxy?url=<encoded>`，后端文件 `backend-web/app/api/routes/chat_new_proxy.py`

---

## 需要实现的功能

请读取参考项目 `D:\Myproject\xianyu-super-butler` 中视频相关的实现，搞清楚以下几点，然后在当前项目中实现：

### 1. 接收视频消息（后端解析）

需要搞清楚：
- 视频消息的 `contentType` 是多少？
- 视频 URL 在哪个字段？（类比图片的 `image.pics[].url`）
- 视频封面图（thumbnail）在哪个字段？

然后在 `common/utils/xianyu_message_parser.py` 的 `interpret_content` 函数中加入视频消息的解析分支，返回格式参考现有的图片处理：返回视频 URL（和封面图 URL）。

同时更新 `chatNew.ts` 里的 `ChatMessage` 类型，加入 `video` 相关字段（如 `videoUrl`、`videoCoverUrl`）。

### 2. 前端展示视频消息

在 `frontend/src/pages/chat-new/ChatNew.tsx` 的消息渲染区域，当 `msg.type === 'video'` 时渲染一个可播放的视频组件，或者渲染封面图+点击播放。视频 URL 也需要走后端代理（参考 `proxyCdnImageUrl` 的做法，可以扩展为 `proxyCdnUrl` 同时支持图片和视频）。

### 3. 发送视频消息（后端）

需要搞清楚：
- 视频如何上传到闲鱼 CDN？（参考项目是否有专门的视频上传器？）
- 发送视频的 IM 协议结构？（payload 里 `contentType` 是多少，字段结构是什么）

然后：
- 在 `backend-web/app/services/chat_new/im_client.py` 里加 `send_video_message` 方法
- 新建 `backend-web/app/api/routes/chat_new_video.py`，参考 `chat_new_image.py` 的结构
- 在 `backend-web/app/api/routes/_exports.py` 注册新路由
- 在 `frontend/src/api/chatNew.ts` 加 `sendVideoMessage` 函数

### 4. 前端发送视频入口

在 `ChatNew.tsx` 的输入区域，在现有图片按钮旁加一个视频上传按钮（`<input accept="video/*">`），选完视频后展示预览（封面帧或文件名），点发送按钮后调用 `sendVideoMessage()` API。

---

## 约束和注意事项

1. **不要修改**已经实现好的图片发送、图片代理、文本发送逻辑，只新增视频相关代码。
2. 后端新路由文件命名为 `chat_new_video.py`，与 `chat_new_image.py` 风格一致。
3. 前端类型 `ChatMessage.type` 从 `'text' | 'image' | 'system' | 'card'` 扩展为加上 `'video'`。
4. `common/utils/xianyu_message_parser.py` 是公共模块，修改时注意同时更新 websocket 端（`websocket/app/services/xianyu/message_handler.py`）使用该函数的地方，确保推送消息也能解析视频。
5. 完成后运行 `cd D:\Myproject\xianyu-auto-reply\frontend && npm run build` 验证前端无编译错误。
6. 最后提交所有变更并 `git push origin main`。

---

## 参考项目路径

`D:\Myproject\xianyu-super-butler`

请先在参考项目里搜索以下关键词，找到视频相关的实现文件后再开始修改当前项目：
- `video`、`视频`、`contentType`（找视频的 contentType 值）
- `send_video`、`upload_video`（找发送/上传接口）
- `VideoUpload`、`video.*url`（找前端相关）
