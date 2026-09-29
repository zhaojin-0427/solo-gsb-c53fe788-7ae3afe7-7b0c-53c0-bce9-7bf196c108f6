# 剪辑素材授权覆盖台

剪辑师在发布前核对时间线素材的使用范围。导入以帧为单位的时间线 JSON，登记授权的素材源帧半开区间、有效日期区间、地区和渠道；选择播出日期、地区、渠道后，逐帧核验每个输出帧上所有活动片段的源帧是否都有授权覆盖，合并连续违规输出帧并在时间轴上定位。

核验全程基于区间运算，**千万帧时间线也不会逐帧展开**；修改授权后可重新核验。

## 技术栈

- 后端：Python + FastAPI + SQLite
- 前端：原生 JavaScript（无框架）
- 部署：Docker Compose

## 启动

```bash
docker compose up --build
```

浏览器访问：<http://localhost:8000>

## 使用流程

1. **新建工程**：点击左侧「＋ 新建工程」，填写工程名称并粘贴时间线 JSON。
2. **登记授权**：在「授权」页签添加授权，填写源帧区间 `[源帧起, 源帧止)`（半开）、有效日期区间、地区、渠道。
3. **核验**：在「核验」页签选择播出日期、地区、渠道，点击「开始核验」。
4. **查看结果**：时间轴上红色为违规帧、蓝色为已覆盖、灰色为空白帧；下方列出每个违规片段的帧区间及各片段的缺口原因（输出帧区间与源帧区间）。
5. 修改授权后再次点击「开始核验」即可重新核验。

## 时间线 JSON 格式

```json
{
  "total_frames": 1000,
  "clips": [
    {
      "name": "片段A",
      "output_start": 0,
      "output_end": 100,
      "source_start": 0,
      "speed": "1/2"
    },
    {
      "name": "片段B",
      "output_start": 50,
      "output_end": 150,
      "source_start": 200,
      "speed": "-1"
    }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `total_frames` | 素材总帧数（源帧有效范围 `[0, total_frames)`） |
| `clips[].name` | 片段名称 |
| `clips[].output_start` / `output_end` | 片段输出半开区间 `[output_start, output_end)` |
| `clips[].source_start` | 源起帧 |
| `clips[].speed` | 非零有符号分数速度，如 `"1/2"`、`"-3/2"`、`"2"`、`"-1"`，也接受数字 |

### 帧映射规则

片段第 `k` 个输出帧（`k` 从 0 开始）映射到源帧：

```
源帧 = source_start + sign(speed) × floor(k × |speed|)
```

- 源帧超出 `[0, total_frames)` 时拒绝核验并报错。
- 授权源帧区间为半开区间 `[source_start, source_end)`。
- 播出日期、地区、渠道三者同时匹配的授权才覆盖该输出帧。
- 空白帧（无活动片段）不算违规。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/projects` | 新建工程（body 含 `name`、`timeline`） |
| GET | `/api/projects` | 工程列表 |
| GET | `/api/projects/{id}` | 工程详情（含时间线） |
| DELETE | `/api/projects/{id}` | 删除工程 |
| POST | `/api/projects/{id}/authorizations` | 添加授权 |
| GET | `/api/projects/{id}/authorizations` | 授权列表 |
| PUT | `/api/authorizations/{id}` | 更新授权 |
| DELETE | `/api/authorizations/{id}` | 删除授权 |
| POST | `/api/projects/{id}/verify` | 核验（body 含 `date`、`region`、`channel`） |

核验返回示例：

```json
{
  "ok": true,
  "violations": [
    {
      "start": 100,
      "end": 250,
      "reasons": [
        {
          "clip_id": "片段A",
          "clip_name": "片段A",
          "output_start": 100,
          "output_end": 200,
          "source_start": 50,
          "source_end": 150
        }
      ]
    }
  ],
  "total_violation_frames": 150
}
```

## 本地开发（不使用 Docker）

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 <http://localhost:8000>。
