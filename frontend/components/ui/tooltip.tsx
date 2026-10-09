"use client"

import * as React from "react"
import {
  TooltipTrigger as RacTooltipTrigger,
  Tooltip as RacTooltip,
} from "react-aria-components"
import { cn } from "cn"

const TooltipDelayContext = React.createContext(0)

function TooltipProvider({
  delay = 0,
  children,
}: {
  delay?: number
  children: React.ReactNode
}) {
  return (
    <TooltipDelayContext.Provider value={delay}>
      {children}
    </TooltipDelayContext.Provider>
  )
}

type TooltipTriggerProps = React.ComponentProps<"button"> & {
  render?: React.ReactElement
  children?: React.ReactNode
  asChild?: boolean
}

function resolveTooltipTrigger(props: TooltipTriggerProps) {
  const { render, children, asChild: _asChild, ...buttonProps } = props
  const trigger = render ?? children
  if (React.isValidElement(trigger)) {
    const triggerProps = trigger.props as React.HTMLAttributes<HTMLElement> & {
      className?: string
      children?: React.ReactNode
    }
    return React.cloneElement(
      trigger,
      {
        ...buttonProps,
        ...triggerProps,
        "data-slot": "tooltip-trigger",
        className: cn(triggerProps.className),
      } as Record<string, unknown>
    )
  }
  if (trigger == null) {
    return null
  }
  return (
    <button type="button" data-slot="tooltip-trigger" {...buttonProps}>
      {trigger}
    </button>
  )
}

function Tooltip({
  children,
  ...props
}: React.ComponentProps<typeof RacTooltipTrigger>) {
  const delay = React.useContext(TooltipDelayContext)
  const triggers: React.ReactNode[] = []
  const rest: React.ReactNode[] = []

  React.Children.forEach(children, (child) => {
    if (React.isValidElement(child) && child.type === TooltipTrigger) {
      triggers.push(resolveTooltipTrigger(child.props as TooltipTriggerProps))
    } else if (child != null && child !== false) {
      rest.push(child)
    }
  })

  return (
    <RacTooltipTrigger data-slot="tooltip" delay={delay} {...props}>
      {triggers}
      {rest}
    </RacTooltipTrigger>
  )
}

function TooltipTrigger(props: TooltipTriggerProps) {
  return <>{props.children}</>
}

type TooltipPlacement = NonNullable<
  React.ComponentProps<typeof RacTooltip>["placement"]
>

function toPlacement(
  side: "top" | "bottom" | "left" | "right" = "top",
  align: "start" | "center" | "end" = "center"
): TooltipPlacement {
  if (align === "center") {
    return side
  }
  return `${side} ${align}` as TooltipPlacement
}

function TooltipContent({
  className,
  side = "top",
  sideOffset = 4,
  align = "center",
  alignOffset = 0,
  children,
  ...props
}: React.ComponentProps<typeof RacTooltip> & {
  side?: "top" | "bottom" | "left" | "right"
  sideOffset?: number
  align?: "start" | "center" | "end"
  alignOffset?: number
}) {
  return (
    <RacTooltip
      data-slot="tooltip-content"
      placement={toPlacement(side, align)}
      offset={sideOffset}
      crossOffset={alignOffset}
      className={cn(
        "z-50 inline-flex w-fit max-w-xs origin-(--transform-origin) items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs text-background has-data-[slot=kbd]:pr-1.5 data-[placement=bottom]:slide-in-from-top-2 data-[placement=inline-end]:slide-in-from-left-2 data-[placement=inline-start]:slide-in-from-right-2 data-[placement=left]:slide-in-from-right-2 data-[placement=right]:slide-in-from-left-2 data-[placement=top]:slide-in-from-bottom-2 **:data-[slot=kbd]:relative **:data-[slot=kbd]:isolate **:data-[slot=kbd]:z-50 **:data-[slot=kbd]:rounded-sm data-entering:animate-in data-entering:fade-in-0 data-entering:zoom-in-95 data-exiting:animate-out data-exiting:fade-out-0 data-exiting:zoom-out-95",
        className
      )}
      {...props}
    >
      {children}
    </RacTooltip>
  )
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider }
