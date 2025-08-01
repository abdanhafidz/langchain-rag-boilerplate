

import warnings
warnings.filterwarnings("ignore")
import asyncio

import gradio as gr
import asyncio
from pipeline.qwen_llm import QwenLLM, QwenConfig
from retriever.langchain_retriever import LangChainRetriever
from inference.inferencer import InferencerConfig, Inferencer

async def test_inference():
    """Main function that sets up and runs the RAG chatbot interface"""
    
    # Initialize RAG components
    print("==== Start Inference Test ===")
    
    # Setup LLM
    config = QwenConfig(
        temperature=0.3,
        max_length=512,
        generation_timeout=9999999.9,
        repetition_penalty=1.1
    )
    
    llm = QwenLLM(config=config)

    # Setup Document Retriever
    document_retriever = LangChainRetriever(
        embedding_model="text-embedding-3-small",
        vectorstore_type="chroma",
        vectorstore_path="./vectorstore",
        use_hybrid_search=True,
        chunk_size=1000, 
        chunk_overlap=200
    )

    # Load initial documents
    file_paths = [
        "../documents/file2.pdf",
    ]
    
    for file_path in file_paths:
        try:
            result = await document_retriever.add_document_from_file(file_path)
            if result.success:
                print(f"Successfully processed: {result.document_metadata.file_name}")
                print(f"Chunks created: {result.document_metadata.chunk_count}")
            else:
                print(f"Failed to process: {result.error_message}")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    # Setup Inferencer
    inferencer_config = InferencerConfig(
        default_k=2,
        enable_reranking=False,
        default_template_types=["system", "friendly", "instruction"]
    )
    
    inferencer = Inferencer(
        model=llm,
        retriever=document_retriever,
        reranker=None,
        config=inferencer_config
    )
    
    print("RAG system initialized successfully!")

    def chatbot_response(message, history):
        """Streaming response menggunakan RAG inferencer"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def stream_response():
                partial_response = ""
                
                async for stream_data in inferencer.infer_stream(
                    query=message,
                    k=3,
                    template_type="friendly"
                ):
                    print(stream_data)
                    if stream_data["type"] == "chunk":
                        chunk = stream_data["data"]["chunk"]
                        partial_response += chunk
                        yield partial_response
                        
                    elif stream_data["type"] == "metadata":
                        setup_time = stream_data['data']['setup_time']
                        print(f"\nSetup completed in {setup_time:.2f}s")
                        
                    elif stream_data["type"] == "complete":
                        total_time = stream_data['data']['total_time']
                        print(f"\nTotal time: {total_time:.2f}s")
            
            # Execute async generator
            async_gen = stream_response()
            
            try:
                while True:
                    result = loop.run_until_complete(async_gen.__anext__())
                    yield result
            except StopAsyncIteration:
                pass
            finally:
                loop.close()
                
        except Exception as e:
            yield f"❌ Error: {str(e)}"

    def add_document_to_vectorstore(file_path):
        """Add document to vectorstore"""
        if not file_path:
            return "⚠️ Please select a file first."
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def add_doc():
                result = await document_retriever.add_document_from_file(file_path)
                return result
            
            result = loop.run_until_complete(add_doc())
            loop.close()
            
            if result.success:
                return f"✅ Successfully added: {result.document_metadata.file_name} ({result.document_metadata.chunk_count} chunks)"
            else:
                return f"❌ Failed to add document: {result.error_message}"
                
        except Exception as e:
            return f"❌ Error adding document: {str(e)}"

    def clear_chat():
        """Function untuk clear chat history"""
        return [], ""

    # CSS untuk styling
    css = """
    .gradio-container {
        max-width: 900px !important;
        margin: auto !important;
    }
    .chat-message {
        padding: 10px;
        margin: 5px;
        border-radius: 10px;
    }
    #chatbot {
        height: 500px;
    }
    """

    # Membuat interface Gradio
    with gr.Blocks(css=css, title="RAG Chatbot") as demo:
        gr.Markdown("""
        # 🤖 RAG Chatbot dengan Text Streaming
        Chatbot berbasis Retrieval-Augmented Generation (RAG) dengan dukungan streaming response.
        """)
        
        # Status indicator
        with gr.Row():
            status_text = gr.Textbox(
                value="✅ RAG System Ready",
                label="System Status",
                interactive=False,
                container=True
            )
        
        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(
                    elem_id="chatbot",
                    show_label=False,
                    container=True,
                    bubble_full_width=False,
                    show_copy_button=True,
                    layout="panel"
                )
                
                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="Tanyakan sesuatu tentang dokumen Anda...",
                        show_label=False,
                        scale=4,
                        container=False,
                        lines=1,
                        max_lines=3,
                        autofocus=True
                    )
                    send_btn = gr.Button("Kirim", variant="primary", scale=1)
                
                with gr.Row():
                    clear_btn = gr.Button("🗑️ Clear Chat", variant="secondary")
                    stop_btn = gr.Button("⏹️ Stop", variant="stop", visible=False)
            
            # Document management panel
            with gr.Column(scale=1):
                gr.Markdown("### 📚 Document Management")
                
                with gr.Group():
                    file_upload = gr.File(
                        label="Upload Document",
                        file_types=[".pdf", ".txt", ".docx"],
                        type="filepath"
                    )
                    upload_btn = gr.Button("Add to Knowledge Base", variant="secondary")
                    upload_status = gr.Textbox(
                        label="Upload Status",
                        interactive=False,
                        lines=3
                    )
                
                gr.Markdown("""
                ### ⚙️ RAG Settings
                - **K**: 3 (documents retrieved)
                - **Template**: Friendly
                - **Reranking**: Disabled
                - **Vectorstore**: ChromaDB
                """)
        
        # State untuk tracking
        is_generating = gr.State(False)
        
        # Event handlers untuk chat
        def user_message(message, history, generating):
            """Handle user message"""
            if message.strip() and not generating:
                history.append([message, None])
                return "", history, True, gr.update(visible=True), gr.update(interactive=False)
            return message, history, generating, gr.update(visible=False), gr.update(interactive=True)
        
        def bot_message_stream(history, generating):
            """Handle streaming bot response"""
            if history and history[-1][1] is None and generating:
                user_msg = history[-1][0]
                
                for partial_response in chatbot_response(user_msg, history):
                    history[-1][1] = partial_response
                    yield history, True, gr.update(visible=True), gr.update(interactive=False)
                
                yield history, False, gr.update(visible=False), gr.update(interactive=True)
            else:
                yield history, generating, gr.update(visible=False), gr.update(interactive=True)
        
        def stop_generation():
            """Stop the generation process"""
            return False, gr.update(visible=False), gr.update(interactive=True)
        
        # Binding events untuk submit message
        submit_event = msg.submit(
            user_message,
            inputs=[msg, chatbot, is_generating],
            outputs=[msg, chatbot, is_generating, stop_btn, send_btn]
        ).then(
            bot_message_stream,
            inputs=[chatbot, is_generating],
            outputs=[chatbot, is_generating, stop_btn, send_btn]
        )
        
        # Binding events untuk send button
        send_event = send_btn.click(
            user_message,
            inputs=[msg, chatbot, is_generating],
            outputs=[msg, chatbot, is_generating, stop_btn, send_btn]
        ).then(
            bot_message_stream,
            inputs=[chatbot, is_generating],
            outputs=[chatbot, is_generating, stop_btn, send_btn]
        )
        
        # Clear chat event
        clear_btn.click(
            clear_chat,
            outputs=[chatbot, msg]
        ).then(
            lambda: (False, gr.update(visible=False), gr.update(interactive=True)),
            outputs=[is_generating, stop_btn, send_btn]
        )
        
        # Stop generation event
        stop_btn.click(
            stop_generation,
            outputs=[is_generating, stop_btn, send_btn],
            cancels=[submit_event, send_event]
        )
        
        # Document upload event
        upload_btn.click(
            add_document_to_vectorstore,
            inputs=[file_upload],
            outputs=[upload_status]
        )
        
        # Info panel
        with gr.Accordion("ℹ️ Info Penggunaan", open=False):
            gr.Markdown("""
            ### Cara Menggunakan:
            1. **Chat**: Ketik pertanyaan tentang dokumen yang sudah dimuat
            2. **Upload**: Tambahkan dokumen baru ke knowledge base
            3. **Stream**: Response akan muncul secara streaming
            4. **Stop**: Gunakan tombol stop untuk menghentikan generasi
            
            ### Dokumen yang Dimuat:
            - file2.pdf (dari folder documents)
            - Dokumen tambahan yang Anda upload
            
            ### Teknologi yang Digunakan:
            - **LLM**: Qwen dengan streaming
            - **Embedding**: text-embedding-3-small
            - **Vectorstore**: ChromaDB
            - **Search**: Hybrid search (dense + sparse)
            """)

    # Launch the interface
    print("Launching Gradio interface...")
    demo.launch(
        share=False,
        server_name="0.0.0.0",
        server_port=7861,
        show_error=True,
        show_api=False
    )


def run_test():
    try:
        # await test_document_retriever()
        # await test_qwen_llm()
        asyncio.run(test_inference())
    except Exception as e:
        print(e)

run_test()