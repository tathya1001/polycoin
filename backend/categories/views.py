from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.mixins import OwnedQuerysetMixin
from transactions.index import in_use

from .models import Category, sort_categories
from .serializers import CategorySerializer, KeywordSerializer


class CategoryViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Category.objects.prefetch_related("keywords")  # one extra query, not one per row
    serializer_class = CategorySerializer

    def list(self, request, *args, **kwargs):
        # Names are encrypted (Phase 12.2, D13), so the database can't sort them: Others first,
        # then A-Z, here.
        categories = sort_categories(self.get_queryset())
        return Response(self.get_serializer(categories, many=True).data)

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()  # 404 for other users' rows, via the mixin
        if category.is_default:
            return Response(
                {"detail": "The default category can't be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            # The database can't see which transactions point here any more (Phase 12.2, D14), so
            # the cores are read, with the category locked: a bulk move into it waits for this.
            Category.objects.select_for_update().filter(pk=category.pk).exists()
            if in_use(request.user, category_id=category.pk):
                return Response(
                    {"detail": "Move its transactions to another category first."},
                    status=status.HTTP_409_CONFLICT,
                )
            category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # Keywords belong to a category, so they live under it. get_object() does the ownership
    # check (404 for someone else's category), so neither action needs its own.
    @action(detail=True, methods=["post"], url_path="keywords")
    def add_keyword(self, request, pk=None):
        category = self.get_object()
        serializer = KeywordSerializer(data=request.data, context={"category": category})
        serializer.is_valid(raise_exception=True)
        serializer.save(category=category)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"keywords/(?P<keyword_id>[0-9a-fA-F-]{36})")
    def remove_keyword(self, request, pk=None, keyword_id=None):
        category = self.get_object()
        deleted, _ = category.keywords.filter(pk=keyword_id).delete()
        if not deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
