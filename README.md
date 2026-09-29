# 剪辑素材授权覆盖台

供剪辑师在发布前核对时间线素材使用范围的服务：导入以帧为单位的时间线、登记素材
授权、选择播出维度（日期 / 地区 / 渠道）后，服务按帧映射规则核验每个活动输出帧所
映射的源帧是否都被授权覆盖，并在时间轴上定位连续违规区间与各片段的缺口原因。

* **后端**：Python · FastAPI · SQLite（标准库 `sqlite3`，无 ORM）
* **前端**：原生 HTML / CSS / JavaScript，无构建步骤
* **部署**：Docker Compose 一键启动
* **核验**：全程整数分数运算 + 区间算法，**千万帧时间线也不逐帧展开**

---

## 一、快速启动

### 方式 A：Docker Compose（推荐）

```bash
docker compose up --build
```

启动后浏览器访问：

> **http://localhost:8000/**

SQLite 数据文件持久化在宿主机 `./data/app.db`（容器内 `/app/data`）。

### 方式 B：本机 Python（3.10+）

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器访问 **http://localhost:8000/** ；交互式 API 文档在
**http://localhost:8000/docs** 。

---

## 二、使用流程

1. 左侧 **新建工程** 并进入；
2. 在「① 时间线导入」粘贴时间线 JSON（可点「载入示例」），点击 **导入时间线**；
3. 在「② 授权登记」按素材登记源帧区间与有效日期 / 地区 / 渠道；
4. 左侧选择 **播出日期、地区、渠道**，点击 **▶ 执行核验**；
5. 结果区显示：
   * 活动帧 / 空白帧 / 违规帧统计与通过/缺口徽标；
   * 时间轴：蓝块为正放片段、紫块为倒放片段，红色斜纹为授权缺口（可横向缩放滚动，
     点击缺口卡片或红块可双向定位）；
   * 每个连续违规运行下保留 **各片段的缺口原因**（无授权登记 / 日期不符 /
     地区不符 / 渠道不符），并列出重叠但维度不匹配的候选授权。
6. **修改授权（增删）后再次点击执行核验即可**，最近一次核验结果随工程持久化。

---

## 三、数据格式

### 3.1 时间线 JSON

所有帧区间均为**半开区间** `[lo, hi)`。

```json
{
  "fps": 25,
  "materials": [
    {
      "id": "MAT-A",
      "total_frames": 10000,
      "segments": [
        { "id": "S1", "in": 0,   "out": 200, "origin": 100,  "speed": 1 },
        { "id": "S2", "in": 200, "out": 350, "origin": 9000, "speed": "-1/2" },
        { "id": "S3", "in": 350, "out": 600, "origin": 5000, "speed": "3/2" }
      ]
    }
  ]
}
```

也支持单素材简写：`{"fps": 25, "total_frames": 10000, "segments": [...]}`。

| 字段 | 含义 |
|---|---|
| `total_frames` | 素材总帧数；合法源帧为 `[0, total_frames)` |
| 片段 `in` / `out` | 输出时间线上的半开帧区间 `[in, out)` |
| `origin` | 片段第 0 个输出帧对应的源帧 |
| `speed` | **非零有符号分数速度**：整数 `2`、字符串 `"3/2"` / `"-1/2"`，或 `{"numerator":3,"denominator":2}`。禁止浮点数与零速度 |

**帧映射规则**：片段第 k 个输出帧（`0 ≤ k < out-in`）映射到源帧

```
src(k) = origin + sign(speed) × floor(k × |speed|)
```

注意负号作用于 `floor` 的结果（倒放），而不是 `floor(负数)`。

### 3.2 授权

授权通过界面或 API 登记，包含：

| 字段 | 含义 |
|---|---|
| `material_id` + `[src_lo, src_hi)` | 被授权的素材源帧半开区间，不得超出 `[0, total_frames)` |
| `[date_from, date_to]` | 有效日期区间，**含首尾**（ISO `YYYY-MM-DD`） |
| `region` / `channel` | 地区与渠道，**精确匹配**（去首尾空格，大小写敏感） |

### 3.3 核验判定

对选定的播出日期 / 地区 / 渠道：

* 某输出帧若有一个或多个**活动片段**，则该帧合法当且仅当它在**每个**活动片段上
  映射出的源帧，都被至少一条日期、地区、渠道同时匹配的授权区间覆盖；
* 没有任何活动片段的**空白帧不算违规**；
* 只要任一片段映射源帧落在 `[0, total_frames)` 之外，核验直接 **rejected**
  （单调性保证只需检查片段端点源帧），并返回越界片段与源帧范围；
* 违规输出帧按授权边界切分后，**合并重叠或相邻（连续）的违规帧**为一个个运行，
  运行上保留造成缺口的每个片段及其原因（含维度不匹配的候选授权清单）。

---

## 四、API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/projects` | 工程列表 |
| POST | `/api/projects` | 新建工程 `{"name": "..."}` |
| GET | `/api/projects/{id}` | 工程详情（含归一化时间线、授权、最近核验结果） |
| PATCH / DELETE | `/api/projects/{id}` | 重命名 / 删除 |
| PUT | `/api/projects/{id}/timeline` | 导入/替换时间线 `{"timeline": {...}}`（重新导入后旧核验结果失效） |
| GET / POST | `/api/projects/{id}/authorizations` | 授权列表 / 登记授权 |
| POST | `/api/projects/{id}/authorizations/batch` | 批量登记 |
| DELETE | `/api/projects/{id}/authorizations/{aid}` | 删除授权 |
| POST | `/api/projects/{id}/verify` | 核验 `{"date":"2026-09-29","region":"CN","channel":"TV"}` |

核验响应（节选）：

```json
{
  "status": "ok",
  "fps": 25,
  "timeline_start": 0,
  "timeline_end": 600,
  "active_frames": 600,
  "blank_frames": 0,
  "violating_frames": 300,
  "violation_run_count": 1,
  "violations": [
    {
      "out": 300, "out_end": 600, "frames": 300,
      "segments": [
        {
          "segment_id": "S3", "material_id": "MAT-A",
          "out": 350, "out_end": 600,
          "src_lo": 5000, "src_hi": 5375,
          "origin": 5000, "speed": "3/2",
          "reason_code": "NO_LICENSE",
          "reason": "该源帧区间没有任何授权登记",
          "candidates": []
        },
        {
          "segment_id": "S4", "material_id": "MAT-B",
          "out": 300, "out_end": 450,
          "src_lo": 0, "src_hi": 300,
          "reason_code": "DIMENSION_MISMATCH",
          "reason": "存在授权但均不匹配：授权地区不匹配",
          "candidates": [ { "id": 3, "mismatch": ["region"] } ]
        }
      ]
    }
  ]
}
```

`status = "rejected"` 时返回 `violations_out_of_bounds`，列出每个越界片段的输出
区间、映射源帧最小/最大值与素材总帧数。

---

## 五、为什么千万帧也不逐帧展开

核验完全以整数区间为单位（见 `app/verification.py`）：

1. **分数全部用整数表示** `p/q`（`q>0`、已约分），`floor(k·|p|/q)` 用整除计算，
   无浮点误差；
2. 片段映射源帧随 k 单调，越界检查只需比较 `k=0` 与 `k=len-1` 两个端点；
3. 对每条授权，把源帧半开区间 `[a_lo, a_hi)` 与片段求交是 **O(1)** 的
   floor/ceil 区间运算（`covered_k_interval`），直接得到被覆盖的 k 区间；
4. 每片段 O(A log A) 合并授权区间、取补集得到缺口，再在输出时间轴上合并为连续
   违规运行，整体复杂度 **O((S + A) log A)**，与总帧数无关；
5. 缺口原因用「起点排序 + 结束点小顶堆」扫描，同样不展开帧。

测试中一千万帧、两条分数速度长片段的核验在毫秒级完成（阈值 3 秒）：

```bash
python -m pytest tests/ -q
```

包含 26 个测试：映射/求交公式单测、越界拒绝、维度不匹配、空白帧、连续合并、
千万帧性能，以及 400 例（另附 5000 例多种子脚本可复现）区间算法与逐帧朴素实现
的随机对拍，结果零偏差。

---

## 六、目录结构

```
app/
  main.py            # FastAPI 路由与输入校验
  verification.py    # 分数帧映射、区间求交/合并、核验主流程（核心算法）
  db.py              # SQLite 持久化
static/
  index.html         # 核验界面
  styles.css
  app.js
tests/               # pytest（含千万帧性能与随机对拍）
Dockerfile
docker-compose.yml
requirements.txt
```
