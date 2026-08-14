from llama_index.core import Document
from llama_index.core.node_parser import SentenceWindowNodeParser
from pathlib import Path


# chunk,基于llama_index的sentencewindownodeparser
text = Path("D:\edge download\MinerU_markdown_A23100070049_2088181842106929152.md").read_text(encoding="utf-8")

