from openai import OpenAI
import os
api_key = "f008da622aee4719a8cdd211a79bfe4d"
api_version = "2023-07-01-preview" 
base_url = "https://oa-northcentral-dev.openai.azure.com/openai/v1/"
deployed_model = "gpt-4o"

# Point to your local Ollama instance
client = OpenAI(
    base_url=base_url,
    api_key=api_key
)

response = client.chat.completions.create(
    model=deployed_model,  # Replace with your downloaded model
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantum computing in one sentence."}
    ]
)

print(response.choices[0].message.content)
