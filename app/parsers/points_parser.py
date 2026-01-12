"""Points parser module"""
from .base_parser import BaseParser


class PointsParser(BaseParser):
    def parse(self):
        raise NotImplementedError

    def extract_content(self, html: str):
        raise NotImplementedError
