import sys
import uuid
import psutil
import threading
from datetime import datetime
import functools
from typing import Optional, Any, Dict, List
from ..utils.unique_decorator import generate_unique_hash_simple, mydecorator
import contextvars
import asyncio
from ..utils.file_name_tracker import TrackName


class CustomTracerMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_tracker = TrackName()
        self.current_custom_name = contextvars.ContextVar("custom_name", default=None)
        self.current_custom_id = contextvars.ContextVar("custom_id", default=None)
        self.component_network_calls = {}
        self.component_user_interaction = {}
        self.gt = None

        # Add auto instrument flags
        self.auto_instrument_custom = False
        self.auto_instrument_user_interaction = False
        self.auto_instrument_network = False

    def trace_custom(self, name: str = None, custom_type: str = "generic", version: str = "1.0.0", trace_variables: bool = True):
        def decorator(func):
            # Add metadata attribute to the function
            metadata = {
                "name": name or func.__name__,
                "custom_type": custom_type,
                "version": version,
                "trace_variables": trace_variables,
                "is_active": True
            }
            
            # Check if the function is async
            is_async = asyncio.iscoroutinefunction(func)

            @self.file_tracker.trace_decorator
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                async_wrapper.metadata = metadata
                self.gt = kwargs.get('gt', None) if kwargs else None
                return await self._trace_custom_execution(
                    func, name or func.__name__, custom_type, version, trace_variables, *args, **kwargs
                )

            @self.file_tracker.trace_decorator
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                sync_wrapper.metadata = metadata
                self.gt = kwargs.get('gt', None) if kwargs else None
                return self._trace_sync_custom_execution(
                    func, name or func.__name__, custom_type, version, trace_variables, *args, **kwargs
                )

            wrapper = async_wrapper if is_async else sync_wrapper
            wrapper.metadata = metadata
            return wrapper

        return decorator

    def _trace_sync_custom_execution(self, func, name, custom_type, version, trace_variables, *args, **kwargs):
        """Synchronous version of custom tracing"""
        if not self.is_active or not self.auto_instrument_custom:
            return func(*args, **kwargs)

        start_time = datetime.now().astimezone().isoformat()
        start_memory = psutil.Process().memory_info().rss
        component_id = str(uuid.uuid4())
        hash_id = generate_unique_hash_simple(func)
        variable_traces = []

        # Set up variable tracing if enabled
        if trace_variables:
            def trace_variables_func(frame, event, arg):
                if event == 'line' and frame.f_code == func.__code__:
                    try:
                        locals_dict = {k: v for k, v in frame.f_locals.items() 
                                     if not k.startswith('__') and isinstance(v, (int, float, bool, str, list, dict, tuple, set))}
                        if locals_dict:
                            variable_traces.append({
                                'variables': locals_dict,
                                'timestamp': datetime.now().astimezone().isoformat()
                            })
                    except:
                        pass
                return trace_variables_func


        # Start tracking network calls for this component
        self.start_component(component_id)

        try:
            # Execute the function
            result = func(*args, **kwargs)

            # Calculate resource usage
            end_time = datetime.now().astimezone().isoformat()
            end_memory = psutil.Process().memory_info().rss
            memory_used = max(0, end_memory - start_memory)

            # End tracking network calls for this component
            self.end_component(component_id)

            # Create custom component
            custom_component = self.create_custom_component(
                component_id=component_id,
                hash_id=hash_id,
                name=name,
                custom_type=custom_type,
                version=version,
                memory_used=memory_used,
                start_time=start_time,
                end_time=end_time,
                variable_traces=variable_traces,
                input_data=self._sanitize_input(args, kwargs),
                output_data=self._sanitize_output(result)
            )

            self.add_component(custom_component)
            return result

        except Exception as e:
            error_component = {
                "code": 500,
                "type": type(e).__name__,
                "message": str(e),
                "details": {}
            }
            
            # End tracking network calls for this component
            self.end_component(component_id)
            
            end_time = datetime.now().astimezone().isoformat()
            
            custom_component = self.create_custom_component(
                component_id=component_id,
                hash_id=hash_id,
                name=name,
                custom_type=custom_type,
                version=version,
                memory_used=0,
                start_time=start_time,
                end_time=end_time,
                variable_traces=variable_traces,
                input_data=self._sanitize_input(args, kwargs),
                output_data=None,
                error=error_component
            )

            self.add_component(custom_component)
            raise

    async def _trace_custom_execution(self, func, name, custom_type, version, trace_variables, *args, **kwargs):
        """Asynchronous version of custom tracing"""
        if not self.is_active or not self.auto_instrument_custom:
            return await func(*args, **kwargs)

        start_time = datetime.now().astimezone().isoformat()
        start_memory = psutil.Process().memory_info().rss
        component_id = str(uuid.uuid4())
        hash_id = generate_unique_hash_simple(func)
        variable_traces = []

        # Set up variable tracing if enabled
        if trace_variables:
            def trace_variables_func(frame, event, arg):
                if event == 'line' and frame.f_code == func.__code__:
                    try:
                        locals_dict = {k: v for k, v in frame.f_locals.items() 
                                     if not k.startswith('__') and isinstance(v, (int, float, bool, str, list, dict, tuple, set))}
                        if locals_dict:
                            variable_traces.append({
                                'variables': locals_dict,
                                'timestamp': datetime.now().astimezone().isoformat()
                            })
                    except:
                        pass
                return trace_variables_func

        try:
            # Execute the function
            result = await func(*args, **kwargs)

            # Calculate resource usage
            end_time = datetime.now().astimezone().isoformat()
            end_memory = psutil.Process().memory_info().rss
            memory_used = max(0, end_memory - start_memory)

            # Create custom component
            custom_component = self.create_custom_component(
                component_id=component_id,
                hash_id=hash_id,
                name=name,
                custom_type=custom_type,
                version=version,
                start_time=start_time,
                end_time=end_time,
                memory_used=memory_used,
                variable_traces=variable_traces,
                input_data=self._sanitize_input(args, kwargs),
                output_data=self._sanitize_output(result)
            )
            self.add_component(custom_component)
            return result

        except Exception as e:
            error_component = {
                "code": 500,
                "type": type(e).__name__,
                "message": str(e),
                "details": {}
            }
            
            end_time = datetime.now().astimezone().isoformat()
            
            custom_component = self.create_custom_component(
                component_id=component_id,
                hash_id=hash_id,
                name=name,
                custom_type=custom_type,
                version=version,
                start_time=start_time,
                end_time=end_time,
                memory_used=0,
                variable_traces=variable_traces,
                input_data=self._sanitize_input(args, kwargs),
                output_data=None,
                error=error_component
            )
            self.add_component(custom_component)
            raise

    def create_custom_component(self, **kwargs):
        """Create a custom component according to the data structure"""
        start_time = kwargs["start_time"]
        
        network_calls = []
        if self.auto_instrument_network:
            network_calls = self.component_network_calls.get(kwargs["component_id"], [])
            
        interactions = []
        if self.auto_instrument_user_interaction:
            interactions = self.component_user_interaction.get(kwargs["component_id"], [])

        component = {
            "id": kwargs["component_id"],
            "hash_id": kwargs["hash_id"],
            "source_hash_id": None,
            "type": "custom",
            "name": kwargs["name"],
            "start_time": start_time,
            "end_time": kwargs["end_time"],
            "error": kwargs.get("error"),
            "parent_id": self.current_agent_id.get() if hasattr(self, 'current_agent_id') else None,
            "info": {
                "custom_type": kwargs["custom_type"],
                "version": kwargs["version"],
                "memory_used": kwargs["memory_used"]
            },
            "data": {
                "input": kwargs["input_data"],
                "output": kwargs["output_data"],
                "memory_used": kwargs["memory_used"],
                "variable_traces": kwargs.get("variable_traces", [])
            },
            "network_calls": network_calls,
            "interactions": interactions
        }

        if self.gt:
            component["data"]["gt"] = self.gt

        return component

    def start_component(self, component_id):
        """Start tracking network calls for a component"""
        self.component_network_calls[component_id] = []

    def end_component(self, component_id):
        """End tracking network calls for a component"""
        pass

    def _sanitize_input(self, args: tuple, kwargs: dict) -> Dict:
        """Sanitize and format input data"""
        return {
            "args": [str(arg) if not isinstance(arg, (int, float, bool, str, list, dict)) else arg for arg in args],
            "kwargs": {
                k: str(v) if not isinstance(v, (int, float, bool, str, list, dict)) else v 
                for k, v in kwargs.items()
            }
        }

    def _sanitize_output(self, output: Any) -> Any:
        """Sanitize and format output data"""
        if isinstance(output, (int, float, bool, str, list, dict)):
            return output
        return str(output)

    # Auto instrumentation methods
    def instrument_custom_calls(self):
        """Enable auto-instrumentation for custom calls"""
        self.auto_instrument_custom = True

    def instrument_user_interaction_calls(self):
        """Enable auto-instrumentation for user interaction calls"""
        self.auto_instrument_user_interaction = True

    def instrument_network_calls(self):
        """Enable auto-instrumentation for network calls"""
        self.auto_instrument_network = True
