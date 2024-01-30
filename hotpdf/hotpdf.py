import math
import os
from collections import defaultdict
from io import IOBase
from pathlib import PurePath
from typing import Optional, Union

from hotpdf import processor
from hotpdf.memory_map import MemoryMap
from hotpdf.utils import filter_adjacent_coords, get_element_dimension, intersect

from .data.classes import ElementDimension, HotCharacter, PageResult, SearchResult, Span


class HotPdf:
    def __init__(
        self,
        pdf_file: Union[PurePath, str, IOBase, None] = None,
        password: str = "",
        drop_duplicate_spans: bool = True,
        first_page: int = 0,
        last_page: int = 0,
        extraction_tolerance: int = 4,
    ) -> None:
        """Initialize the HotPdf class.

        Args:
            pdf_file (PurePath | str | IOBytes): The path to the PDF file to be loaded, or a bytes object.
            password (str, optional): Password to use to unlock the pdf
            drop_duplicate_spans (bool, optional): Drop duplicate spans when loading. Defaults to True.
            first_page (int, optional): The first page to load (1-indexed). Defaults to 0 (will load full PDF).
            last_page (int, optional): The last page to load (1-indexed). Defaults to 0 (will load full PDF).
            extraction_tolerance (int, optional): Tolerance value used during text extraction
                to adjust the bounding box for capturing text. Defaults to 4.

        Raises:
            ValueError: If the page range is invalid.
            FileNotFoundError: If the file is not found.
            PermissionError: If the file is encrypted or the password is wrong.
            RuntimeError: If an unkown error is generated by transfotmer.
        """
        self.pages: list[MemoryMap] = []
        self.extraction_tolerance: int = extraction_tolerance
        if pdf_file:
            self.load(pdf_file, password, drop_duplicate_spans, first_page, last_page)

    def __check_file_exists(self, pdf_file: str) -> None:
        if not os.path.exists(pdf_file):
            raise FileNotFoundError(f"File {pdf_file} not found")

    def __check_coordinates(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if x0 < 0 or x1 < 0 or y0 < 0 or y1 < 0:
            raise ValueError("Invalid coordinates")

    def __check_page_number(self, page: int) -> None:
        if page < 0 or page >= len(self.pages):
            raise ValueError("Invalid page number")

    def __check_page_range(self, first_page: int, last_page: int) -> None:
        if first_page > last_page or first_page < 0 or last_page < 0:
            raise ValueError("Invalid page range")

    def __prechecks(self, pdf_file: Union[PurePath, str, IOBase], first_page: int, last_page: int) -> None:
        if type(pdf_file) is str:
            self.__check_file_exists(pdf_file)
        self.__check_page_range(first_page, last_page)

    def load(
        self,
        pdf_file: Union[PurePath, str, IOBase],
        password: str = "",
        drop_duplicate_spans: bool = True,
        first_page: int = 0,
        last_page: int = 0,
    ) -> None:
        """Load a PDF file into memory.

        Args:
            pdf_file (str | Bytes): The path to the PDF file to be loaded, or a bytes object.
            password (str, optional): Password to use to unlock the pdf
            drop_duplicate_spans (bool, optional): Drop duplicate spans when loading. Defaults to True.
            first_page (int, optional): The first page to load. Defaults to 0.
            last_page (int, optional): The last page to load. Defaults to 0.

        Raises:
            Exception: If an unknown error is generated by pdfminer.
        """
        self.__prechecks(pdf_file, first_page, last_page)
        try:
            self.pages = processor.process(pdf_file, password, drop_duplicate_spans, first_page, last_page)
        except Exception as e:
            raise e

    def __extract_full_text_span(
        self,
        hot_characters: list[HotCharacter],
        page_num: int,
    ) -> Union[list[HotCharacter], None]:
        """Extract the full span of text that the given hot characters are a part of.

        Args:
            hot_characters (list[HotCharacter]): the list of hot characters to extract the span for.
            page_num (int): the page number of the hot characters.

        Returns:
            Union[list[HotCharacter], None]: the full span of text that the hot characters are a part of.
        """
        _span: Optional[Span] = None
        if hot_characters[0].span_id:
            _span = self.pages[page_num].span_map[hot_characters[0].span_id]
        return _span.characters if _span else None

    def find_text(
        self,
        query: str,
        pages: Optional[list[int]] = None,
        validate: bool = True,
        take_span: bool = False,
        sort: bool = True,
    ) -> SearchResult:
        """Find text within the loaded PDF pages.

        Args:
            query (str): The text to search for.
            pages (list[int], optional): List of page numbers to search.
            validate (bool, optional): Double check the extracted bounding boxes with the query string.
            take_span (bool, optional): Take the full span of the text that it is a part of.
            sort (bool, Optional): Return elements sorted by their positions.
        Raises:
            ValueError: If the page number is invalid.

        Returns:
            SearchResult: A dictionary mapping page numbers to found text coordinates.
        """
        if pages is None:
            pages = []

        for page in pages:
            self.__check_page_number(page)

        query_pages = (
            {i: self.pages[i] for i in range(len(self.pages))} if len(pages) == 0 else {i: self.pages[i] for i in pages}
        )

        found_page_map = {}

        for page_num in query_pages:
            found_page_map[page_num] = filter_adjacent_coords(*query_pages[page_num].find_text(query))

        final_found_page_map: SearchResult = defaultdict(PageResult)

        for page_num in found_page_map:
            hot_character_page_occurences: PageResult = found_page_map[page_num]
            final_found_page_map[page_num] = []
            for hot_characters in hot_character_page_occurences:
                element_dimension = get_element_dimension(hot_characters)
                text = self.extract_text(
                    x0=element_dimension.x0,
                    y0=element_dimension.y0,
                    x1=element_dimension.x1,
                    y1=element_dimension.y1,
                    page=page_num,
                )
                if (query in text) or not validate:
                    seen_span_ids: list[str] = []
                    full_span_dimension_hot_characters: Union[list[HotCharacter], None] = (
                        self.__extract_full_text_span(
                            hot_characters=hot_characters,
                            page_num=page_num,
                        )
                        if take_span
                        else None
                    )
                    chars_to_append = (
                        full_span_dimension_hot_characters
                        if (take_span and full_span_dimension_hot_characters)
                        else hot_characters
                    )
                    if chars_to_append:
                        if chars_to_append[0].span_id in seen_span_ids:
                            continue
                        seen_span_ids.extend(list(set([ch.span_id for ch in chars_to_append])))
                        if sort:
                            chars_to_append = sorted(chars_to_append, key=lambda ch: (ch.x, ch.y))
                    final_found_page_map[page_num].append(chars_to_append)
        return final_found_page_map

    def extract_spans(self, x0: int, y0: int, x1: int, y1: int, page: int = 0) -> list[Span]:
        """Extract spans that intersect with the given bounding box.

        Args:
            x0 (int): The left x-coordinate of the bounding box.
            y0 (int): The bottom y-coordinate of the bounding box.
            x1 (int): The right x-coordinate of the bounding box.
            y1 (int): The top y-coordinate of the bounding box.
            page (int, optional): The page number. Defaults to 0.
            sort (bool, optional): Sort the spans by their coordinates. Defaults to True.

        Raises:
            ValueError: If the coordinates are invalid.
            ValueError: If the page number is invalid.

        Returns:
            list[Span]: List of spans of hotcharacters that intersect with the given bounding box
        """
        spans: list[Span] = []

        self.__check_coordinates(x0, y0, x1, y1)
        self.__check_page_number(page)

        for _, span in self.pages[page].span_map.items():
            if intersect(ElementDimension(x0, y0, x1, y1, ""), span.get_element_dimension()):
                spans.append(span)
        return spans

    def extract_text(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        page: int = 0,
    ) -> str:
        """Extract text from a specified bounding box on a page.

        Args:
            x0 (int): The left x-coordinate of the bounding box.
            y0 (int): The bottom y-coordinate of the bounding box.
            x1 (int): The right x-coordinate of the bounding box.
            y1 (int): The top y-coordinate of the bounding box.
            page (int): The page number. Defaults to 0.

        Raises:
            ValueError: If the coordinates are invalid.
            ValueError: If the page number is invalid.

        Returns:
            str: Extracted text within the bounding box.
        """
        self.__check_coordinates(x0, y0, x1, y1)
        self.__check_page_number(page)

        page_to_search: MemoryMap = self.pages[page]
        extracted_text = page_to_search.extract_text_from_bbox(
            x0=math.floor(x0),
            x1=math.ceil(x1 + self.extraction_tolerance),
            y0=y0,
            y1=y1,
        )
        return extracted_text

    def extract_page_text(
        self,
        page: int,
    ) -> str:
        """Extract text from a specified page.

        Args:
            page (int): The page number.

        Raises:
            ValueError: If the page number is invalid.

        Returns:
            str: Extracted text from the page.
        """
        self.__check_page_number(page)

        page_to_search: MemoryMap = self.pages[page]
        extracted_text = page_to_search.extract_text_from_bbox(
            x0=0,
            x1=page_to_search.width,
            y0=0,
            y1=page_to_search.height,
        )
        return extracted_text

    def extract_spans_text(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        page: int = 0,
    ) -> str:
        """Extract text from spans that intersect with the given bounding box.

        Args:
            x0 (int): The left x-coordinate of the bounding box.
            y0 (int): The bottom y-coordinate of the bounding box.
            x1 (int): The right x-coordinate of the bounding box.
            y1 (int): The top y-coordinate of the bounding box.
            page (int, optional): The page number. Defaults to 0.

        Raises:
            ValueError: If the coordinates are invalid.
            ValueError: If the page number is invalid.

        Returns:
            str: Extracted text that intersects with the bounding box.
        """
        self.__check_coordinates(x0, y0, x1, y1)
        self.__check_page_number(page)

        spans: list[Span] = self.extract_spans(x0, y0, x1, y1, page)
        extracted_text: list[str] = []

        for span in spans:
            extracted_text.append(span.to_text())
        return "".join(extracted_text)
