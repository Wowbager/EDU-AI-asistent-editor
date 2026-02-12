"""
Example usage of the refactored webchat architecture.

This file demonstrates how to use the new clean architecture components
for common tasks. Copy these patterns into your code as needed.
"""

import asyncio
from typing import List

# ============================================================================
# EXAMPLE 1: Using Domain Models
# ============================================================================

async def example_domain_models():
    """Demonstrate domain model usage."""
    from domain import ConversationState, Course, Lecture, Quiz
    from domain.quiz import QuizQuestion, QuizAnswer
    
    # Create conversation state
    state = ConversationState(
        sender_id="user123",
        current_course="1",
        gpt_conversation="edu",
        gpt_conversation_counter=5
    )
    
    print(f"State: {state.sender_id}, course: {state.current_course}")
    
    # Convert to legacy slots format
    slots = state.to_slots()
    print(f"Legacy slots: {slots['current_course']}")
    
    # Restore from legacy slots
    restored = ConversationState.from_slots("user123", slots)
    print(f"Restored counter: {restored.gpt_conversation_counter}")
    
    # Create quiz question
    question = QuizQuestion(
        text="What is 2+2?",
        options=[
            QuizAnswer(text="3", is_correct=False),
            QuizAnswer(text="4", is_correct=True),
            QuizAnswer(text="5", is_correct=False),
        ]
    )
    
    formatted = question.format_with_buttons()
    print(f"Formatted question:\n{formatted}")


# ============================================================================
# EXAMPLE 2: Using Repositories
# ============================================================================

async def example_repositories():
    """Demonstrate repository usage."""
    from service_container import get_container
    from core.constants import SlotKeys
    
    # Get container (must be initialized first)
    container = get_container()
    
    # Use slot repository
    sender_id = "user123"
    
    # Get conversation state
    state = await container.slot_repo.get_conversation_state(sender_id)
    print(f"Current course: {state.current_course}")
    
    # Update state
    state.current_course = "42"
    state.gpt_conversation = "edu"
    await container.slot_repo.save_conversation_state(state)
    
    # Or update single slot
    await container.slot_repo.set_slot(
        sender_id,
        SlotKeys.GPT_CONVERSATION_COUNTER,
        "10"
    )
    
    # Use course repository
    course = await container.course_repo.get_course_by_id(1)
    if course:
        print(f"Course: {course.name}")
        
        # Get first lecture
        lecture = await container.course_repo.get_first_lecture_in_course(
            course.id
        )
        if lecture:
            print(f"First lecture: {lecture.name}")
            
            # Get lecture steps
            steps = await container.course_repo.get_root_steps(lecture.id)
            for step in steps:
                print(f"  Step {step.position}: {step.text}")
    
    # Use task repository
    tasks = await container.task_repo.get_active_tasks(sender_id)
    print(f"Active tasks: {len(tasks)}")


# ============================================================================
# EXAMPLE 3: Using Infrastructure Services
# ============================================================================

async def example_infrastructure():
    """Demonstrate infrastructure service usage."""
    from service_container import get_container
    from core.prompts import PromptBuilder, ConversationMode
    
    container = get_container()
    
    # Rate limiting
    sender_id = "user123"
    if await container.rate_limiter.allow(sender_id):
        print("Request allowed")
    else:
        print("Rate limit exceeded")
    
    # LLM client
    response = await container.llm_client.get_response(
        message="Hello, how are you?",
        use_ollama=False
    )
    print(f"LLM response: {response}")
    
    # Or with chat history
    chat_history = [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "What is Python?"}
    ]
    response = await container.llm_client.get_response(
        chat_history=chat_history
    )
    print(f"LLM response: {response}")
    
    # Slot cache
    slots = await container.slot_cache.get_slots(sender_id)
    print(f"Cached slots: {slots}")
    
    await container.slot_cache.set_slot(sender_id, "test_key", "test_value")


# ============================================================================
# EXAMPLE 4: Using Constants and Prompts
# ============================================================================

async def example_constants_prompts():
    """Demonstrate constants and prompt usage."""
    from core.constants import (
        SlotKeys, ConversationMode, SpecialMessages,
        ResponseLimits, ActionNames
    )
    from core.prompts import (
        SystemPrompts, ResponseTemplates, PromptBuilder
    )
    
    # Check special messages
    user_message = "/get_started"
    if user_message == SpecialMessages.GET_STARTED:
        print("User wants to start conversation")
    
    # Check conversation mode
    gpt_mode = "edu"
    if gpt_mode == ConversationMode.EDUCATIONAL:
        max_messages = ResponseLimits.MAX_CONVERSATION_EDU
        print(f"Educational mode, max messages: {max_messages}")
    
    # Build AI prompt
    prompt = PromptBuilder.build_conversation_prompt(
        mode=ConversationMode.BRIEF,
        course_description="Learn Python programming",
        chat_history=[
            {"role": "user", "content": "Tell me about loops"}
        ]
    )
    print(f"Prompt has {len(prompt)} messages")
    
    # Use response templates
    reset_msg = ResponseTemplates.RESET_CONFIRMED
    error_msg = ResponseTemplates.ERROR_RATE_LIMIT
    print(f"Reset message: {reset_msg}")


# ============================================================================
# EXAMPLE 5: Building Custom Action Executor
# ============================================================================

async def example_custom_action_executor():
    """Demonstrate how to create a custom action executor."""
    from core.action_interface import ActionExecutor
    from typing import Any, List
    
    class MyCustomExecutor:
        """Example custom action executor."""
        
        def __init__(self, llm_client, repositories):
            self.llm = llm_client
            self.repos = repositories
        
        async def run(
            self,
            dispatcher: Any,
            tracker: Any,
            domain: Any = None
        ) -> List[Any]:
            """Execute custom action logic."""
            sender_id = tracker.current_state()["sender_id"]
            user_text = tracker.latest_message.get("text", "")
            
            # Get conversation state
            state = await self.repos['slot'].get_conversation_state(sender_id)
            
            # Check if we should use AI
            if state.gpt_conversation:
                # Build prompt
                from core.prompts import PromptBuilder
                
                prompt = PromptBuilder.build_conversation_prompt(
                    mode=state.gpt_conversation,
                    course_description="",
                    chat_history=[
                        {"role": "user", "content": user_text}
                    ]
                )
                
                # Get LLM response
                response = await self.llm.get_response(
                    chat_history=prompt
                )
                
                dispatcher.utter_message(text=response)
            else:
                # Handle course navigation
                if state.current_course:
                    course = await self.repos['course'].get_course_by_id(
                        int(state.current_course)
                    )
                    if course:
                        dispatcher.utter_message(
                            text=f"You're in course: {course.name}"
                        )
            
            return []
    
    # Usage (in service container initialization)
    from service_container import get_container
    
    container = get_container()
    custom_executor = MyCustomExecutor(
        llm_client=container.llm_client,
        repositories={
            'course': container.course_repo,
            'slot': container.slot_repo,
            'task': container.task_repo,
        }
    )
    
    print("Custom executor created")


# ============================================================================
# EXAMPLE 6: Complete Request Flow
# ============================================================================

async def example_complete_flow():
    """Demonstrate a complete request flow."""
    from service_container import get_container
    from core.constants import SlotKeys, SpecialMessages
    from core.prompts import ResponseTemplates
    
    container = get_container()
    sender_id = "user123"
    user_message = "Tell me about Python"
    
    # 1. Check rate limiting
    if not await container.rate_limiter.allow(sender_id):
        return ResponseTemplates.ERROR_RATE_LIMIT
    
    # 2. Load conversation state
    state = await container.slot_repo.get_conversation_state(sender_id)
    
    # 3. Check for special commands
    if user_message.lower() in ["reset", "restart"]:
        await container.slot_repo.reset_all_slots(sender_id)
        await container.task_repo.reset_all_tasks(sender_id)
        return ResponseTemplates.RESET_CONFIRMED
    
    # 4. Handle conversation based on mode
    if state.gpt_conversation:
        # AI conversation mode
        from core.prompts import PromptBuilder
        
        course_desc = ""
        if state.current_course:
            course = await container.course_repo.get_course_by_id(
                int(state.current_course)
            )
            course_desc = course.description if course else ""
        
        prompt = PromptBuilder.build_conversation_prompt(
            mode=state.gpt_conversation,
            course_description=course_desc,
            chat_history=[
                {"role": "user", "content": user_message}
            ]
        )
        
        response = await container.llm_client.get_response(
            chat_history=prompt,
            use_ollama=state.use_gemma
        )
        
        # Update counter
        state.gpt_conversation_counter += 1
        await container.slot_repo.save_conversation_state(state)
        
        return response
    else:
        # Course navigation mode
        if state.current_course:
            course = await container.course_repo.get_course_by_id(
                int(state.current_course)
            )
            if course:
                return f"You are in course: {course.name}"
        
        return "Please select a course to begin."


# ============================================================================
# MAIN: Run Examples
# ============================================================================

async def main():
    """Run all examples."""
    from service_container import initialize_container
    from config import get_settings
    
    settings = get_settings()
    
    # Initialize container
    print("Initializing service container...")
    await initialize_container(
        redis_url=settings.redis_url,
        slot_cache_ttl=3600,
        rate_limit_max=20
    )
    
    print("\n" + "="*70)
    print("EXAMPLE 1: Domain Models")
    print("="*70)
    await example_domain_models()
    
    print("\n" + "="*70)
    print("EXAMPLE 2: Repositories")
    print("="*70)
    await example_repositories()
    
    print("\n" + "="*70)
    print("EXAMPLE 3: Infrastructure")
    print("="*70)
    await example_infrastructure()
    
    print("\n" + "="*70)
    print("EXAMPLE 4: Constants & Prompts")
    print("="*70)
    await example_constants_prompts()
    
    print("\n" + "="*70)
    print("EXAMPLE 5: Custom Action Executor")
    print("="*70)
    await example_custom_action_executor()
    
    print("\n" + "="*70)
    print("EXAMPLE 6: Complete Flow")
    print("="*70)
    response = await example_complete_flow()
    print(f"Response: {response}")
    
    # Cleanup
    from service_container import shutdown_container
    await shutdown_container()
    print("\n✅ All examples completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
