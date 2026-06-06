# TVBox Source Keeper

每天检查一组经过登记的公开 TVBox、直播和 EPG 地址，剔除失效项，按连续
成功次数和响应延迟排序，然后通过 GitHub 固定地址发布一个不变的
`tvbox.json` 地址。

## 固定地址

在 TVBox 中填写：

```text
https://raw.githubusercontent.com/wangsu20M/tvbox/main/public/tvbox.json
```

机器可读状态：

```text
https://raw.githubusercontent.com/wangsu20M/tvbox/main/public/status.json
```

## 工作方式

- `config/candidates.json` 保存候选配置、直播列表、EPG 和公开发现清单。
- 每天读取 IPTV.org 的国家与分类 API，自动发现配置中选定的公开目录。
- GitHub Actions 每天北京时间 03:23 运行，也可以手动运行。
- 检查结果直接提交回 `main`，无需配置 GitHub Pages。
- 最多并发检查 12 个候选，每个候选默认超时 12 秒。
- JSON、M3U/TVBox 文本直播列表和 XMLTV 均会做格式验证。
- 状态报告会统计每个可用播放列表及其频道条目数量。
- 对播放列表内的频道 URL 做并发媒体探测，去重后生成 `public/live.m3u`。
- TVBox 只引用仓库生成的已探测直播列表，不再直接加载全部上游条目。
- 默认优先中国及周边公开目录、仅保留 HTTPS，并输出中文分组。
- GitHub 只生成境外发现候选 `public/candidates.m3u`；墙内可播结果由本机
  直连检测生成 `public/live.m3u`。
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

### 墙内直连筛选

GitHub 和 Cloudflare 都是境外节点，不能判断关闭代理后能否播放。Windows
本地筛选器会明确忽略 `HTTP_PROXY`、`HTTPS_PROXY` 和系统代理：

```powershell
python local_filter.py
```

每天自动运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_local_task.ps1
```

任务默认每天 04:10 运行。电脑关机时会在下次开机后补跑。GitHub 拉取和
推送允许使用 `127.0.0.1:10808`，但频道媒体检测始终强制直连。

生成文件位于 `public/`：

- `tvbox.json`：TVBox 使用的固定配置
- `live.m3u`：逐条探测后生成的直播列表
- `candidates.m3u`：GitHub 境外节点发现的候选列表
- `status.json`：机器可读的检查报告
- `index.html`：可视化状态页

项目默认仅带两个声明为公开免费频道的直播候选和一个社区 EPG。影视点播
接口需要权利方授权后再加入；不要把私人网盘凭据提交到公开仓库。
