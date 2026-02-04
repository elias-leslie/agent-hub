# OpenRouter Integration Test Script
#!/bin/bash

echo "🧪 Testing OpenRouter Integration"

cd /home/kasadis/agent-hub/backend

# Test 1: Adapter Import
echo "1. Testing adapter import..."
python -c "
import sys
sys.path.append('.')
try:
    from app.adapters.openrouter import OpenRouterAdapter, resolve_openrouter_model
    print('✅ Adapter import: SUCCESS')
except ImportError as e:
    print('❌ Adapter import: FAILED')
    print(f'Error: {e}')
    exit 1
"

# Test 2: Provider Detection
echo "2. Testing provider detection..."
python -c "
import sys
sys.path.append('.')
from app.api.complete.helpers import get_provider

test_models = [
    'openrouter/anthropic/claude-3.5-sonnet',
    'openrouter/openai/gpt-4o',
    'or/sonnet',
    'or/gpt4o',
    'claude-3.5-sonnet'  # Should detect claude, not openrouter
]

print('🔍 Testing model resolution...')
for model in test_models:
    provider = get_provider(model)
    expected = 'openrouter' if 'openrouter/' in model or 'or/' in model else provider
    status = '✅' if expected in model and 'openrouter' in provider or expected not in model and 'openrouter' not in provider else '❌'
    print(f'  {model} → {provider} {status}')
"

# Test 3: Adapter Factory
echo "3. Testing adapter factory..."
python -c "
import sys
sys.path.append('.')

from app.api.complete.helpers import get_adapter

try:
    # Should fail with API key error, not import error
    adapter = get_adapter('openrouter')
    print('❌ Expected API key error, but got:', type(adapter))
except ValueError as e:
    if 'API key' in str(e):
        print('✅ Factory: correctly requires API key')
    else:
        print('❌ Factory error:', e)
except Exception as e:
    print('❌ Factory failed:', e)
"

echo "🎯 OpenRouter integration tests completed!"