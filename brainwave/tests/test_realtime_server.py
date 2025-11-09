import pytest
from fastapi.testclient import TestClient
from realtime_server import app, ReadabilityRequest, CorrectnessRequest, AskAIRequest
import json
from unittest.mock import patch, AsyncMock, MagicMock

client = TestClient(app)

@pytest.fixture
def mock_llm_processor():
    with patch('realtime_server.llm_processor') as mock:
        # Setup for sync processing
        mock.process_text_sync.return_value = "Mocked response"
        
        # Setup for async processing
        async def text_generator():
            yield "Mocked"
            yield " streaming"
            yield " response"
        mock.process_text.return_value = text_generator()
        
        yield mock

def test_enhance_readability(mock_llm_processor):
    request = ReadabilityRequest(text="Test text")
    response = client.post("/api/v1/readability", json=request.model_dump())
    assert response.status_code == 200
    assert "Mocked streaming response" in response.text

def test_check_correctness(mock_llm_processor):
    request = CorrectnessRequest(text="Test fact checking")
    response = client.post("/api/v1/correctness", json=request.model_dump())
    assert response.status_code == 200
    assert "Mocked streaming response" in response.text

def test_ask_ai(mock_llm_processor):
    request = AskAIRequest(text="What is the meaning of life?")
    response = client.post("/api/v1/ask_ai", json=request.model_dump())
    assert response.status_code == 200
    assert response.json()["answer"] == "Mocked response"

@pytest.mark.asyncio
async def test_websocket_endpoint():
    with patch('realtime_server.OpenAIRealtimeAudioTextClient') as mock_client:
        mock_instance = AsyncMock()
        mock_client.return_value = mock_instance
        mock_instance.connect = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_instance.process_audio = AsyncMock(return_value={"text": "test"})

        with client.websocket_connect("/api/v1/ws") as websocket:
            # Send a test message
            data = {
                "audio": "base64_encoded_audio_data",
                "timestamp": "2024-01-01T00:00:00"
            }
            websocket.send_json(data)
            
            # Verify we get a response
            response = websocket.receive_json()
            assert "type" in response

def test_get_realtime_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
