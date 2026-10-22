from django.urls import path
from .views import search_view, governed_query_view

urlpatterns = [
    path('search/', search_view, name='retrieval-search'),
    path('query/', governed_query_view, name='retrieval-query'),
]
