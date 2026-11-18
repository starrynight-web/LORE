from django.urls import path
from .views import graph_overview_view, node_lineage_view

urlpatterns = [
    path('graph-overview/', graph_overview_view, name='knowledge-graph-overview'),
    path('node/<str:node_id>/lineage/', node_lineage_view, name='knowledge-node-lineage'),
]
