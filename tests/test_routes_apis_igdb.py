import pytest
from unittest.mock import patch
from uuid import uuid4

from oneirodex.models import User, Game, Library
from oneirodex.platform import LibraryPlatform

pytestmark = [
    pytest.mark.integration,  # A3.1: kept out of the fast `-m "not integration"` core -- IGDB provider API surface.
    pytest.mark.usefixtures('reusable_secret_keyring'),
]


def assert_igdb_query(mock_request, endpoint, expected_query):
    """Keep provider fields and values significant while allowing query indentation to change."""
    mock_request.assert_called_once()
    actual_endpoint, actual_query = mock_request.call_args.args
    assert actual_endpoint == endpoint
    assert actual_query.split() == expected_query.split()


@pytest.fixture
def admin_user(db_session):
    """Create an admin user for testing."""
    admin_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=admin_uuid,
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    """Create a regular user for testing."""
    user_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=user_uuid,
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        is_email_verified=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def mock_involved_companies_response():
    """Mock IGDB involved_companies API response."""
    return [
        {
            'company': {'name': 'Test Company'},
            'developer': True,
            'publisher': False,
            'game': 12345
        }
    ]


@pytest.fixture
def mock_cover_response():
    """Mock IGDB cover API response."""
    return 'https://images.igdb.com/igdb/image/upload/t_thumb/test_cover.jpg'


@pytest.fixture
def mock_game_data():
    """Mock IGDB game data response."""
    return {
        'id': 12345,
        'name': 'Test Game',
        'summary': 'A test game',
        'cover': 1234,
        'screenshots': [5678],
        'genres': [{'name': 'Action'}],
        'platforms': [{'name': 'PC'}],
        'first_release_date': 1234567890
    }


@pytest.fixture
def sample_game(db_session):
    """Create a sample game in the database."""
    # Create a library first
    unique_id = str(uuid4())[:8]
    library = Library(
        name=f'Test Library_{unique_id}',
        platform=LibraryPlatform.PCWIN
    )
    db_session.add(library)
    db_session.flush()  # Get the library UUID
    
    # Create the game with a unique IGDB ID to avoid conflicts
    game = Game(
        igdb_id=888888,  # Use a different ID to avoid conflicts with other tests
        name='Existing Game',
        library_uuid=library.uuid,
        full_disk_path='/test/path'
    )
    db_session.add(game)
    db_session.commit()
    return game


class TestGetCompanyRole:
    """Tests for get_company_role endpoint."""
    
    def test_get_company_role_requires_login(self, client):
        """Test that get_company_role requires login."""
        response = client.get('/api/get_company_role?game_igdb_id=123&company_id=456')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_get_company_role_missing_parameters(self, client, admin_user):
        """Test get_company_role with missing parameters."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # Missing both parameters
        response = client.get('/api/get_company_role')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'Invalid input. Both game_igdb_id and company_id must be provided and numeric.'
        
        # Missing company_id
        response = client.get('/api/get_company_role?game_igdb_id=123')
        assert response.status_code == 400
        
        # Missing game_igdb_id
        response = client.get('/api/get_company_role?company_id=456')
        assert response.status_code == 400
    
    def test_get_company_role_invalid_parameters(self, client, admin_user):
        """Test get_company_role with invalid parameters."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # Non-numeric game_igdb_id
        response = client.get('/api/get_company_role?game_igdb_id=abc&company_id=456')
        assert response.status_code == 400
        data = response.get_json()
        assert data['error'] == 'Invalid input. Both game_igdb_id and company_id must be provided and numeric.'
        
        # Non-numeric company_id
        response = client.get('/api/get_company_role?game_igdb_id=123&company_id=xyz')
        assert response.status_code == 400
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_successful_developer(self, mock_api_request, client, admin_user, mock_involved_companies_response):
        """Test successful get_company_role for developer."""
        mock_api_request.return_value = mock_involved_companies_response
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['game_igdb_id'] == '12345'
        assert data['company_id'] == '789'
        assert data['company_name'] == 'Test Company'
        assert data['role'] == 'Developer'
        
        # Verify API call
        assert_igdb_query(
            mock_api_request, "https://api.igdb.com/v4/involved_companies",
            "fields company.name, developer, publisher, game;\n                where game=12345 & id=(789);"
        )
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_successful_publisher(self, mock_api_request, client, admin_user):
        """Test successful get_company_role for publisher."""
        mock_response = [
            {
                'company': {'name': 'Publisher Company'},
                'developer': False,
                'publisher': True,
                'game': 12345
            }
        ]
        mock_api_request.return_value = mock_response
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['role'] == 'Publisher'
        assert data['company_name'] == 'Publisher Company'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_not_found(self, mock_api_request, client, admin_user):
        """Test get_company_role with role not found."""
        mock_response = [
            {
                'company': {'name': 'Other Company'},
                'developer': False,
                'publisher': False,
                'game': 12345
            }
        ]
        mock_api_request.return_value = mock_response
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['role'] == 'Not Found'
        assert data['company_name'] == 'Other Company'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_api_error(self, mock_api_request, client, admin_user):
        """Test get_company_role with API error."""
        mock_api_request.return_value = {'error': 'API Error'}
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 404
        
        data = response.get_json()
        assert data['error'] == 'No data found or error in response.'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_empty_response(self, mock_api_request, client, admin_user):
        """Test get_company_role with empty response."""
        mock_api_request.return_value = []
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 404
        
        data = response.get_json()
        assert data['error'] == 'No data found or error in response.'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_invalid_company_structure(self, mock_api_request, client, admin_user):
        """Test get_company_role with invalid company data structure."""
        mock_response = [
            {
                'company': 'Invalid Company Data',  # Should be dict, not string
                'developer': True,
                'publisher': False,
                'game': 12345
            }
        ]
        mock_api_request.return_value = mock_response
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 404
        
        data = response.get_json()
        assert data['error'] == 'Company with given ID not found in the specified game.'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_get_company_role_exception(self, mock_api_request, client, admin_user):
        """Test get_company_role with exception during processing."""
        mock_api_request.side_effect = Exception("Connection error")
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_company_role?game_igdb_id=12345&company_id=789')
        assert response.status_code == 500
        
        data = response.get_json()
        assert data['error'] == 'An error occurred processing your request.'


class TestGetCoverThumbnail:
    """Tests for get_cover_thumbnail endpoint."""
    
    def test_get_cover_thumbnail_requires_login(self, client):
        """Test that get_cover_thumbnail requires login."""
        response = client.get('/api/get_cover_thumbnail?igdb_id=123')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_get_cover_thumbnail_missing_parameter(self, client, admin_user):
        """Test get_cover_thumbnail with missing igdb_id."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_cover_thumbnail')
        assert response.status_code == 400
        
        data = response.get_json()
        assert data['error'] == 'Invalid input. The ID must be numeric.'
    
    def test_get_cover_thumbnail_invalid_parameter(self, client, admin_user):
        """Test get_cover_thumbnail with non-numeric igdb_id."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_cover_thumbnail?igdb_id=abc')
        assert response.status_code == 400
        
        data = response.get_json()
        assert data['error'] == 'Invalid input. The ID must be numeric.'
    
    @patch('oneirodex.utils.igdb_api.get_cover_thumbnail_url')
    def test_get_cover_thumbnail_successful(self, mock_get_cover, client, admin_user, mock_cover_response):
        """Test successful get_cover_thumbnail."""
        mock_get_cover.return_value = mock_cover_response
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_cover_thumbnail?igdb_id=12345')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['cover_url'] == mock_cover_response
        
        mock_get_cover.assert_called_once_with(12345)
    
    @patch('oneirodex.utils.igdb_api.get_cover_thumbnail_url')
    def test_get_cover_thumbnail_not_found(self, mock_get_cover, client, admin_user):
        """Test get_cover_thumbnail when cover URL cannot be retrieved."""
        mock_get_cover.return_value = None
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/get_cover_thumbnail?igdb_id=12345')
        assert response.status_code == 404
        
        data = response.get_json()
        assert data['error'] == 'Cover URL could not be retrieved.'


class TestSearchIgdbById:
    """Tests for search_igdb_by_id endpoint."""
    
    def test_search_igdb_by_id_requires_login(self, client):
        """Test that search_igdb_by_id requires login."""
        response = client.get('/api/search_igdb_by_id?igdb_id=123')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_search_igdb_by_id_missing_parameter(self, client, admin_user):
        """Test search_igdb_by_id with missing igdb_id."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_id')
        assert response.status_code == 400
        
        data = response.get_json()
        assert data['error'] == 'IGDB ID is required'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_id_successful(self, mock_api_request, client, admin_user, mock_game_data):
        """Test successful search_igdb_by_id."""
        mock_api_request.return_value = [mock_game_data]
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_id?igdb_id=12345')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['id'] == 12345
        assert data['name'] == 'Test Game'
        assert data['summary'] == 'A test game'
        
        # Verify API call with correct query
        expected_query = """
        fields id, name, cover, summary, url, release_dates.date, platforms.name, genres.name, themes.name, game_modes.name,
               screenshots, videos.video_id, first_release_date, aggregated_rating, involved_companies, player_perspectives.name,
               aggregated_rating_count, rating, rating_count, slug, status, category, total_rating, 
               total_rating_count, storyline;
        where id = 12345;
    """
        assert_igdb_query(mock_api_request, "https://api.igdb.com/v4/games", expected_query)
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_id_api_error(self, mock_api_request, client, admin_user):
        """Test search_igdb_by_id with API error."""
        mock_api_request.return_value = {'error': 'API connection failed'}
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_id?igdb_id=12345')
        assert response.status_code == 500
        
        data = response.get_json()
        assert data['error'] == 'API connection failed'
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_id_not_found(self, mock_api_request, client, admin_user):
        """Test search_igdb_by_id when game not found."""
        mock_api_request.return_value = []
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_id?igdb_id=99999')
        assert response.status_code == 404
        
        data = response.get_json()
        assert data['error'] == 'Game not found'


class TestSearchIgdbByName:
    """Tests for search_igdb_by_name endpoint."""
    
    def test_search_igdb_by_name_requires_login(self, client):
        """Test that search_igdb_by_name requires login."""
        response = client.get('/api/search_igdb_by_name?name=Test')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_search_igdb_by_name_missing_parameter(self, client, admin_user):
        """Test search_igdb_by_name with missing name parameter."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_name')
        # Was 200 with an error body — a client branching on status saw success
        # for a missing required parameter. The only consumer
        # (admin_game_identify.js) never checked status, so nothing relied on it.
        assert response.status_code == 400

        data = response.get_json()
        assert data['error'] == 'No game name provided'
        assert data['error_code'] == 'bad_request'
        assert data['ok'] is False
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_name_successful(self, mock_api_request, client, admin_user, mock_game_data):
        """Test successful search_igdb_by_name."""
        mock_api_request.return_value = [mock_game_data]
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_name?name=Test Game')
        assert response.status_code == 200
        
        data = response.get_json()
        assert 'results' in data
        assert len(data['results']) == 1
        assert data['results'][0]['name'] == 'Test Game'
        
        # Verify API call
        expected_query = '''fields id, name, cover, summary, url, release_dates.date, platforms.name, genres.name, themes.name, game_modes.name,
                          screenshots, videos.video_id, first_release_date, aggregated_rating, involved_companies, player_perspectives.name,
                          aggregated_rating_count, rating, rating_count, slug, status, category, total_rating, 
                          total_rating_count, storyline;search "Test Game"; limit 10;'''
        assert_igdb_query(mock_api_request, 'https://api.igdb.com/v4/games', expected_query)
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_name_with_platform(self, mock_api_request, client, admin_user, mock_game_data):
        """Test search_igdb_by_name with platform filter."""
        mock_api_request.return_value = [mock_game_data]
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_name?name=Test Game&platform_id=6')
        assert response.status_code == 200
        
        data = response.get_json()
        assert 'results' in data
        
        # Verify API call includes platform filter
        expected_query = '''fields id, name, cover, summary, url, release_dates.date, platforms.name, genres.name, themes.name, game_modes.name,
                          screenshots, videos.video_id, first_release_date, aggregated_rating, involved_companies, player_perspectives.name,
                          aggregated_rating_count, rating, rating_count, slug, status, category, total_rating, 
                          total_rating_count, storyline;search "Test Game"; where platforms = (6); limit 10;'''
        assert_igdb_query(mock_api_request, 'https://api.igdb.com/v4/games', expected_query)
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_name_invalid_platform(self, mock_api_request, client, admin_user, mock_game_data):
        """Test search_igdb_by_name with invalid platform_id."""
        mock_api_request.return_value = [mock_game_data]
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_name?name=Test Game&platform_id=abc')
        assert response.status_code == 200
        
        # Should ignore invalid platform_id and not include it in query
        expected_query = '''fields id, name, cover, summary, url, release_dates.date, platforms.name, genres.name, themes.name, game_modes.name,
                          screenshots, videos.video_id, first_release_date, aggregated_rating, involved_companies, player_perspectives.name,
                          aggregated_rating_count, rating, rating_count, slug, status, category, total_rating, 
                          total_rating_count, storyline;search "Test Game"; limit 10;'''
        assert_igdb_query(mock_api_request, 'https://api.igdb.com/v4/games', expected_query)
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_search_igdb_by_name_api_error(self, mock_api_request, client, admin_user):
        """Test search_igdb_by_name with API error."""
        mock_api_request.return_value = {'error': 'Search failed'}
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/search_igdb_by_name?name=Test Game')
        # Was 200 with an error body. An IGDB failure is an upstream fault, so
        # it answers 502 now — `bad_gateway` distinguishes "the provider broke"
        # from "we broke" (`internal`) and "it is switched off" (`unavailable`).
        assert response.status_code == 502

        data = response.get_json()
        assert data['error'] == 'Search failed'
        assert data['error_code'] == 'bad_gateway'


class TestCheckIgdbId:
    """Tests for check_igdb_id endpoint."""
    
    def test_check_igdb_id_requires_login(self, client):
        """Test that check_igdb_id requires login."""
        response = client.get('/api/check_igdb_id?igdb_id=123')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_check_igdb_id_missing_parameter(self, client, admin_user):
        """Test check_igdb_id with missing igdb_id."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/check_igdb_id')
        assert response.status_code == 400
        
        data = response.get_json()
        assert data['message'] == 'Invalid request'
        assert data['available'] is False
    
    def test_check_igdb_id_invalid_parameter(self, client, admin_user):
        """Test check_igdb_id with non-numeric igdb_id."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/check_igdb_id?igdb_id=abc')
        assert response.status_code == 400
        
        data = response.get_json()
        assert data['message'] == 'Invalid request'
        assert data['available'] is False
    
    def test_check_igdb_id_available(self, client, admin_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/api/check_igdb_id?igdb_id=12345')
        assert response.status_code == 200
        assert response.get_json()['available'] is True

    def test_check_igdb_id_not_available(self, client, admin_user, sample_game):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get(f'/api/check_igdb_id?igdb_id={sample_game.igdb_id}')
        assert response.status_code == 200
        assert response.get_json()['available'] is False


class TestIgdbApiRoutes:
    def test_igdb_routes_register_head_alongside_get(self, client, admin_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        for route in ('get_company_role', 'get_cover_thumbnail', 'search_igdb_by_id',
                      'search_igdb_by_name', 'check_igdb_id'):
            endpoint = '/api/' + route
            get = client.get(endpoint)
            head = client.head(endpoint)
            assert get.status_code == head.status_code == 400, endpoint
            assert head.data == b'', endpoint
            assert head.headers['Content-Length'] == get.headers['Content-Length'], endpoint

    def test_igdb_routes_authentication_required(self, client):
        """Test that all IGDB API routes require authentication."""
        endpoints = [
            '/api/get_company_role?game_igdb_id=123&company_id=456',
            '/api/get_cover_thumbnail?igdb_id=123',
            '/api/search_igdb_by_id?igdb_id=123',
            '/api/search_igdb_by_name?name=test',
            '/api/check_igdb_id?igdb_id=123'
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 302
            assert 'login' in response.location


class TestIgdbApiIntegration:
    """Integration tests for IGDB API routes."""
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_igdb_api_workflow_search_and_check(self, mock_api_request, client, admin_user, mock_game_data):
        """Test complete workflow: search by name, then check if ID is available."""
        mock_api_request.return_value = [mock_game_data]
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # First search by name
        search_response = client.get('/api/search_igdb_by_name?name=Test Game')
        assert search_response.status_code == 200
        search_data = search_response.get_json()
        
        # Then check if the found game's ID is available
        game_id = search_data['results'][0]['id']
        check_response = client.get(f'/api/check_igdb_id?igdb_id={game_id}')
        assert check_response.status_code == 200
        check_data = check_response.get_json()
        
        # Should be available since we haven't added it to our database
        assert check_data['available'] is True
    
    def test_igdb_error_handling_consistency(self, client, admin_user):
        """Test that error responses follow consistent format."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # Test various error scenarios
        responses = [
            client.get('/api/get_company_role'),  # Missing parameters
            client.get('/api/get_cover_thumbnail'),  # Missing parameter
            client.get('/api/search_igdb_by_id'),  # Missing parameter
            client.get('/api/check_igdb_id'),  # Missing parameter
        ]
        
        for response in responses:
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data or 'message' in data
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    @patch('oneirodex.utils.igdb_api.get_cover_thumbnail_url')
    def test_igdb_cover_integration(self, mock_get_cover, mock_api_request, client, admin_user, mock_game_data, mock_cover_response):
        """Test integration between game search and cover retrieval."""
        mock_api_request.return_value = [mock_game_data]
        mock_get_cover.return_value = mock_cover_response
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # Search for game
        search_response = client.get('/api/search_igdb_by_id?igdb_id=12345')
        assert search_response.status_code == 200
        
        # Get cover for the same game
        cover_response = client.get('/api/get_cover_thumbnail?igdb_id=12345')
        assert cover_response.status_code == 200
        
        cover_data = cover_response.get_json()
        assert cover_data['cover_url'] == mock_cover_response
