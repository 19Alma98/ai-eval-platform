# Tracing

Export OTLP spans to OpenGrade and annotate them.

Use the methods of your `Opengrade` instance: `og.trace`, `og.span`, `og.set_user`, … They take
the same arguments as the module-level functions documented below, and always go to that
instance. The module-level functions go to the instance activated with `og.activate()`.

::: opengrade._opengrade.Opengrade.trace

::: opengrade._opengrade.Opengrade.span

::: opengrade._opengrade.Opengrade.init_tracing

::: opengrade._otel.flush

::: opengrade._trace.trace

::: opengrade._trace.span

::: opengrade._trace.SpanHandle

::: opengrade._trace.current_trace_id

::: opengrade._trace.set_input

::: opengrade._trace.set_output

::: opengrade._trace.set_error

::: opengrade._trace.set_attribute

::: opengrade._trace.set_attributes

::: opengrade._trace_attrs.set_user

::: opengrade._trace_attrs.set_session

::: opengrade._trace_attrs.set_tags

::: opengrade._trace_attrs.set_metadata

::: opengrade._trace_attrs.using_attributes
