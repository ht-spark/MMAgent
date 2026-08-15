## 一、子功能区简介

##### 目标：辅助智能体的本地知识库也就是RAG功能。用户可以在这里和结合了专用知识库的LLM交流，思考方法，形成一个初步的建模思路，或者得到自己想要的内容。

##### 核心功能：可以把这里的建模思路加载到任务智能体里面，控制引导智能体进行建模，智能体每次任务完成也可以由用户选择是否将这次任务的报告文档放入知识库

## 二、功能模块原型设计

### 1.文档上传
##### 1) 用户可以上传单个文件或者压缩包文件夹；
##### 2) 上传后前端需要实时展示当前任务的信息，包括：给上传的每一份文件加一个唯一标识，文件名称，上传时间，是否上传成功，这里以表格的形式展示；
##### 3）等上传完成后，如果存在不是markdown格式的文件，则调用mineru API转换为markdown格式，如果全部都是markdown格式，则直接进行下一步操作

#### 2.并自动切片嵌入本地向量数据库



#### 2.基于LLM进行可视化交流

## 三、检索策略

    用户题目
                       ↓
               Query Analyzer
                       ↓
               Problem Router
                       ↓
          ┌────────────┴────────────┐
          ↓                         ↓
    Metadata Filter            Query Rewrite
          │                         │
          └────────────┬────────────┘
                       ↓
             ┌───────────────────┐
             │ Hybrid Retrieval  │
             │                   │
             │ Dense        BM25 │
             │   ↓            ↓  │
             │ Top 30      Top 30│
             └─────────┬─────────┘
                       ↓
                      RRF
                       ↓
                   Top 30~50
                       ↓
                Cross Encoder
                  Reranker
                       ↓
                    Top 5~8
                       ↓
             Parent Expansion
                       ↓
                Context Dedup
                       ↓
                      LLM

## 四、技术细节

#### 基于LlamaIndex实习

#### 嵌入模型

    Qwen3-Embedding-0.6B

#### 向量数据库

    Qdrant

## 五、架构

    upload_file.py -> 实现文档上传以及markdown格式转换，完成数据准备
    chunk_embedding.py -> 实现文档chunk和向量数据库的嵌入
    vectorstore.py -> 创建和部署本地向量数据库
    interface.py -> 实现用户与基于本地知识库的LLM的交互
