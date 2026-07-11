from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Default page size 25; clients may request up to 100 via ?page_size=."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
