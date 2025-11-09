import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os
from llm_processor import GeminiProcessor, GPTProcessor, get_llm_processor

@pytest.fixture
def mock_env_vars():
    with patch.dict(os.environ, {
        'GOOGLE_API_KEY': 'test_google_key',
        'OPENAI_API_KEY': 'test_openai_key'
    }):
        yield

@pytest.fixture
def mock_genai():
    with patch('llm_processor.genai') as mock:
        mock_model_instance = AsyncMock()
        mock.GenerativeModel.return_value = mock_model_instance
        mock_model_instance.generate_content = MagicMock(
            return_value=MagicMock(text="Test response")
        )
        yield mock

@pytest.fixture
def mock_openai():
    with patch('llm_processor.AsyncOpenAI') as mock_async_openai, \
         patch('llm_processor.OpenAI') as mock_openai:
        mock_async_client = AsyncMock()
        mock_client = MagicMock()
        
        # Setup sync client mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
        mock_client.chat.completions.create.return_value = mock_response
        
        # Setup async client mock
        async def async_gen():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="Hello"))])
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=" World"))])
        
        mock_async_client.chat.completions.create = AsyncMock(return_value=async_gen())
        
        mock_async_openai.return_value = mock_async_client
        mock_openai.return_value = mock_client
        yield mock_async_openai, mock_openai, mock_async_client, mock_client

class TestGeminiProcessor:
    def test_init_no_api_key(self):
        with patch.dict(os.environ, clear=True):
            with pytest.raises(EnvironmentError, match="GOOGLE_API_KEY is not set"):
                GeminiProcessor()

    def test_init_success(self, mock_env_vars, mock_genai):
        processor = GeminiProcessor()
        assert processor.default_model == 'gemini-1.5-pro'
        mock_genai.configure.assert_called_once_with(api_key='test_google_key')

    @pytest.mark.asyncio
    async def test_process_text(self, mock_env_vars, mock_genai):
        mock_model = mock_genai.GenerativeModel.return_value
        async def async_gen():
            for chunk in [MagicMock(text="Hello"), MagicMock(text=" World")]:
                yield chunk
        mock_model.generate_content_async.return_value = async_gen()

        processor = GeminiProcessor()
        result = []
        async for chunk in processor.process_text("input", "prompt"):
            result.append(chunk)
        assert result == ["Hello", " World"]
        mock_genai.GenerativeModel.return_value.generate_content_async.assert_called_once()

    def test_process_text_sync(self, mock_env_vars, mock_genai):
        processor = GeminiProcessor()
        result = processor.process_text_sync("input", "prompt")
        assert result == "Test response"
        mock_genai.GenerativeModel.return_value.generate_content.assert_called_once()

class TestGPTProcessor:
    def test_init_no_api_key(self):
        with patch.dict(os.environ, clear=True):
            with pytest.raises(ValueError, match="OpenAI API key not found in environment variables"):
                GPTProcessor()

    def test_init_success(self, mock_env_vars, mock_openai):
        mock_async_class, mock_class, _, _ = mock_openai
        processor = GPTProcessor()
        assert processor.default_model == 'gpt-4'
        mock_async_class.assert_called_once_with(api_key='test_openai_key')
        mock_class.assert_called_once_with(api_key='test_openai_key')

    @pytest.mark.asyncio
    async def test_process_text(self, mock_env_vars, mock_openai):
        processor = GPTProcessor()
        result = []
        async for chunk in processor.process_text("input", "prompt"):
            result.append(chunk)
        assert result == ["Hello", " World"]

    def test_process_text_sync(self, mock_env_vars, mock_openai):
        processor = GPTProcessor()
        result = processor.process_text_sync("input", "prompt")
        assert result == "Test response"

def test_get_llm_processor_gemini(mock_env_vars, mock_genai):
    processor = get_llm_processor("gemini-1.5-pro")
    assert isinstance(processor, GeminiProcessor)

def test_get_llm_processor_gpt(mock_env_vars, mock_openai):
    processor = get_llm_processor("gpt-4")
    assert isinstance(processor, GPTProcessor)

def test_get_llm_processor_unknown(mock_env_vars):
    with pytest.raises(ValueError, match="Unsupported model type:"):
        get_llm_processor("unknown-model")
