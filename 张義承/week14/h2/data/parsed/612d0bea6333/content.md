# 612d0bea6333


## 第 1 页

多模态 RAG 测试文档
第一章 系统架构
本系统通过 Kafka 把 PDF 上传任务从 Web 层传
递给解析 worker，worker 使用 MinerU 或
 PyMuPDF 解析文档，提取文本与图片，再按标题和长度切
块后存储，供后续检索使用。
图 1：一张红色测试图片

![](/files/parsed/612d0bea6333/images/page1_img1.png)


## 第 2 页

第二章 检索与问答
检索采用 BM25 算法对切块打分，取分数最高的若干片段作为
上下文。回答阶段把检索到的资料和用户问题一起发送给 Deep
Seek 多模态模型，模型可以结合用户上传的图片进行回答，输
出 Markdown 图文混排结果。
