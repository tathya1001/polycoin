class OwnedQuerysetMixin:
    """Mixin for DRF views/viewsets whose queryset must be scoped to the requesting user.

    Combine with an OwnedModel-based model. Every view that uses this mixin
    automatically only ever sees rows the current user owns, and automatically
    attaches the current user when a new row is created.
    """

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
