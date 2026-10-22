from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils.text import slugify
from .models import Organization, OrganizationMembership
from .serializers import UserSerializer, OrganizationSerializer, OrganizationMembershipSerializer

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

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def me_view(request):
    memberships = OrganizationMembership.objects.filter(user=request.user).select_related('organization')
    orgs = [m.organization for m in memberships]
    return Response({
        'user': UserSerializer(request.user).data,
        'organizations': OrganizationSerializer(orgs, many=True, context={'request': request}).data
    })

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
