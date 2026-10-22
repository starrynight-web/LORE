from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils.text import slugify
from .models import Organization, OrganizationMembership, OrganizationInvitation
from .serializers import (
    UserSerializer, 
    OrganizationSerializer, 
    OrganizationMembershipSerializer, 
    OrganizationInvitationSerializer
)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def register_view(request):
    username = request.data.get('username')
    email = request.data.get('email', '')
    password = request.data.get('password')
    org_name = request.data.get('organization_name', f"{username}'s Organization")

    if not username or not password:
        return Response({'error': 'Username and password are required.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({'error': 'User with this username already exists.'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(username=username, email=email, password=password)
    token, _ = Token.objects.get_or_create(user=user)

    # Automatically create default organization
    base_slug = slugify(org_name) or 'org'
    slug = base_slug
    counter = 1
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization.objects.create(name=org_name, slug=slug)
    OrganizationMembership.objects.create(organization=org, user=user, role='owner')

    return Response({
        'token': token.key,
        'user': UserSerializer(user).data,
        'organization': OrganizationSerializer(org, context={'request': request}).data
    }, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def login_view(request):
    username = request.data.get('username')
    password = request.data.get('password')

    user = authenticate(username=username, password=password)
    if not user:
        return Response({'error': 'Invalid username or password.'}, status=status.HTTP_401_UNAUTHORIZED)

    token, _ = Token.objects.get_or_create(user=user)
    memberships = OrganizationMembership.objects.filter(user=user).select_related('organization')
    orgs = [m.organization for m in memberships]

    return Response({
        'token': token.key,
        'user': UserSerializer(user).data,
        'organizations': OrganizationSerializer(orgs, many=True, context={'request': request}).data
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout_view(request):
    """Revokes the user's active authentication token."""
    if hasattr(request.user, 'auth_token'):
        request.user.auth_token.delete()
    return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def me_view(request):
    memberships = OrganizationMembership.objects.filter(user=request.user).select_related('organization')
    orgs = [m.organization for m in memberships]
    return Response({
        'user': UserSerializer(request.user).data,
        'organizations': OrganizationSerializer(orgs, many=True, context={'request': request}).data
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def accept_invitation_view(request):
    """Accepts an organization invitation token and links the user."""
    token = request.data.get('token')
    if not token:
        return Response({'error': 'Invitation token is required.'}, status=status.HTTP_400_BAD_REQUEST)

    invitation = OrganizationInvitation.objects.filter(token=token).first()
    if not invitation:
        return Response({'error': 'Invalid or unknown invitation token.'}, status=status.HTTP_404_NOT_FOUND)

    if invitation.is_accepted:
        return Response({'error': 'Invitation has already been accepted.'}, status=status.HTTP_400_BAD_REQUEST)

    if invitation.is_expired():
        return Response({'error': 'Invitation token has expired.'}, status=status.HTTP_400_BAD_REQUEST)

    # Add user to organization with specified role
    membership, created = OrganizationMembership.objects.get_or_create(
        organization=invitation.organization,
        user=request.user,
        defaults={'role': invitation.role}
    )
    if not created and membership.role != invitation.role:
        membership.role = invitation.role
        membership.save(update_fields=['role'])

    invitation.is_accepted = True
    invitation.save(update_fields=['is_accepted'])

    return Response({
        'message': f'Successfully joined {invitation.organization.name} as {invitation.role}.',
        'organization': OrganizationSerializer(invitation.organization, context={'request': request}).data
    }, status=status.HTTP_200_OK)

class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Organization.objects.filter(memberships__user=self.request.user)

    def perform_create(self, serializer):
        name = serializer.validated_data.get('name')
        base_slug = slugify(name) or 'org'
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        org = serializer.save(slug=slug)
        OrganizationMembership.objects.create(organization=org, user=self.request.user, role='owner')

    from rest_framework.decorators import action
    from datetime import timedelta
    import secrets
    from django.utils import timezone

    @action(detail=True, methods=['get', 'post'], url_path='invitations')
    def invitations(self, request, pk=None):
        org = self.get_object()
        user_mem = OrganizationMembership.objects.filter(organization=org, user=request.user).first()
        if not user_mem or user_mem.role not in ('owner', 'admin'):
            return Response({'error': 'Only organization owners or administrators can manage invitations.'}, status=status.HTTP_403_FORBIDDEN)

        if request.method == 'GET':
            invites = org.invitations.filter(is_accepted=False).order_by('-created_at')
            return Response(OrganizationInvitationSerializer(invites, many=True).data)

        # POST: Create invitation
        email = request.data.get('email')
        role = request.data.get('role', 'member')
        if not email:
            return Response({'error': 'Email is required for invitation.'}, status=status.HTTP_400_BAD_REQUEST)
        if role not in ('owner', 'admin', 'member', 'viewer'):
            return Response({'error': 'Invalid role specified.'}, status=status.HTTP_400_BAD_REQUEST)

        # Generate secure random token expiring in 7 days
        import secrets
        from datetime import timedelta
        from django.utils import timezone
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(days=7)

        invite = OrganizationInvitation.objects.create(
            organization=org,
            email=email,
            role=role,
            invited_by=request.user,
            token=token,
            expires_at=expires_at
        )

        return Response(OrganizationInvitationSerializer(invite).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='members')
    def members(self, request, pk=None):
        org = self.get_object()
        memberships = org.memberships.select_related('user').all()
        return Response(OrganizationMembershipSerializer(memberships, many=True).data)

    @action(detail=True, methods=['patch', 'delete'], url_path=r'members/(?P<member_id>[^/.]+)')
    def member_detail(self, request, pk=None, member_id=None):
        org = self.get_object()
        caller_mem = OrganizationMembership.objects.filter(organization=org, user=request.user).first()
        if not caller_mem or caller_mem.role not in ('owner', 'admin'):
            return Response({'error': 'Administrative privileges required.'}, status=status.HTTP_403_FORBIDDEN)

        target_mem = OrganizationMembership.objects.filter(organization=org, id=member_id).first()
        if not target_mem:
            return Response({'error': 'Member not found in organization.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            # Cannot delete the only owner
            if target_mem.role == 'owner' and org.memberships.filter(role='owner').count() <= 1:
                return Response({'error': 'Cannot remove the sole owner of the organization.'}, status=status.HTTP_400_BAD_REQUEST)
            target_mem.delete()
            return Response({'message': 'Member removed from organization.'}, status=status.HTTP_200_OK)

        if request.method == 'PATCH':
            new_role = request.data.get('role')
            if new_role not in ('owner', 'admin', 'member', 'viewer'):
                return Response({'error': 'Invalid role specified.'}, status=status.HTTP_400_BAD_REQUEST)
            # If demoting an owner, ensure another owner exists
            if target_mem.role == 'owner' and new_role != 'owner' and org.memberships.filter(role='owner').count() <= 1:
                return Response({'error': 'Cannot demote the sole owner of the organization.'}, status=status.HTTP_400_BAD_REQUEST)
            target_mem.role = new_role
            target_mem.save(update_fields=['role'])
            return Response(OrganizationMembershipSerializer(target_mem).data)
