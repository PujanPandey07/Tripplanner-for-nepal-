from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="llama3.1:8b"
)
hello = llm.invoke("Hello, how are you?")
print(hello)
