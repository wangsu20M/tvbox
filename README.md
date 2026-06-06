# TVBox Source Keeper

每天检查一组经过登记的公开 TVBox、直播和 EPG 地址，剔除失效项，按连续
成功次数和响应延迟排序，然后通过 GitHub Pages 发布一个不变的
`tvbox.json` 地址。

## 固定地址

仓库发布后，在 TVBox 中填写：

```text
https://<你的 GitHub 用户名>.github.io/<仓库名>/tvbox.json
```

状态页：

```text
https://<你的 GitHub 用户名>.github.io/<仓库名>/
```

## 工作方式

- `config/candidates.json` 保存候选配置、直播列表、EPG 和公开发现清单。
- GitHub Actions 每天北京时间 03:23 运行，也可以手动运行。
- 最多并发检查 12 个候选，每个候选默认超时 12 秒。
- JSON、M3U/TVBox 文本直播列表和 XMLTV 均会做格式验证。
- 内网地址、非 HTTP(S) 地址以及疑似 Cookie、Token、Authorization
  等账号凭据会被拒绝。
- 连续可用天数越多、响应越快，评分越高；不可用源不会进入发布配置。
- `data/state.json` 保存连续成功和失败次数，用于跨天稳定性排序。

## 添加来源

编辑 `config/candidates.json`：

```json
{
  "discovery_feeds": [
    {
      "name": "自己维护的公开登记表",
      "url": "https://example.com/tvbox-sources.json"
    }
  ],
  "tvbox_configs": [
    {
      "name": "合法公开 TVBox 配置",
      "url": "https://example.com/tvbox.json"
    }
  ],
  "live_playlists": [
    {
      "name": "公开直播",
      "url": "https://example.com/live.m3u",
      "epg": "https://example.com/epg.xml"
    }
  ],
  "epg_sources": [
    {
      "name": "公开 EPG",
      "url": "https://example.com/epg.xml"
    }
  ]
}
```

发现清单使用相同的顶层字段。项目只聚合明确登记的公开地址，不上传视频，
也不收集夸克、UC、百度网盘 Cookie 或其他账号凭据。对互联网做无边界爬取
既无法保证覆盖“全网”，也容易发布恶意配置或未授权内容，因此发现与发布
之间必须保留白名单和自动审计。

## 本地运行

```powershell
python tvbox_aggregator.py
python -m unittest discover -s tests -v
```

生成文件位于 `public/`：

- `tvbox.json`：TVBox 使用的固定配置
- `status.json`：机器可读的检查报告
- `index.html`：可视化状态页

## GitHub Pages 设置

1. 推送仓库。
2. 打开仓库 `Settings > Pages`。
3. 将 `Build and deployment > Source` 设为 `GitHub Actions`。
4. 在 `Actions` 中手动运行一次 `Update TVBox sources`。

项目默认仅带两个声明为公开免费频道的直播候选和一个社区 EPG。影视点播
接口需要权利方授权后再加入；不要把私人网盘凭据提交到公开仓库。
