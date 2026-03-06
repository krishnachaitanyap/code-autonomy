import pytest
from fastapi.testclient import TestClient
from src.api.routes.ask import router
from src.api.schemas import AskRequest

client = TestClient(router)

def test_ask_question_success(mocker):
    mocker.patch('src.services.agent_service.AgentService.run_ask', return_value=mocker.Mock(success=True, answer='Test answer', sources=[], turns_used=1))
    
    response = client.post('/', json={'repo_id': 'test_repo', 'question': 'What is this?'})
    
    assert response.status_code == 200
    assert response.json() == {
        'success': True,
        'answer': 'Test answer',
        'sources': [],
        'turns_used': 1
    }

def test_ask_question_repo_not_found(mocker):
    mocker.patch('src.data.repositories.RepoRepository.get_by_id', return_value=None)
    
    response = client.post('/', json={'repo_id': 'invalid_repo', 'question': 'What is this?'})
    
    assert response.status_code == 404
    assert response.json() == {'detail': 'Repository not found'}

def test_ask_question_repo_path_invalid(mocker):
    mocker.patch('src.data.repositories.RepoRepository.get_by_id', return_value=mocker.Mock(local_path=None))
    
    response = client.post('/', json={'repo_id': 'test_repo', 'question': 'What is this?'})
    
    assert response.status_code == 400
    assert 'Repository path does not exist' in response.json()['detail']

def test_ask_question_no_api_key(mocker):
    mocker.patch('src.services.config_service.ConfigService.load_config', return_value={})
    
    response = client.post('/', json={'repo_id': 'test_repo', 'question': 'What is this?'})
    
    assert response.status_code == 400
    assert 'No LLM API key configured' in response.json()['detail']