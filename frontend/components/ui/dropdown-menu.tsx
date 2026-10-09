"use client"

import * as React from "react"
import {
  MenuTrigger,
  Menu,
  MenuItem as RacMenuItem,
  MenuSection,
  Popover,
  SubmenuTrigger,
  Separator,
  Header,
} from "react-aria-components"
import { cn } from "cn"
import { ChevronRightIcon, CheckIcon } from "lucide-react"

type PopoverPlacement = NonNullable<React.ComponentProps<typeof Popover>["placement"]>

function toPlacement(
  side: "top" | "bottom" | "left" | "right" | "inline-start" | "inline-end" = "bottom",
  align: "start" | "center" | "end" = "start"
): PopoverPlacement {
  if (align === "center") {
    return side as PopoverPlacement
  }
  return `${side} ${align}` as PopoverPlacement
}

type DropdownMenuTriggerProps = React.ComponentProps<"button"> & {
  render?: React.ReactElement
  children?: React.ReactNode
  asChild?: boolean
}

function resolveDropdownMenuTrigger(props: DropdownMenuTriggerProps) {
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
        "data-slot": "dropdown-menu-trigger",
        className: cn(triggerProps.className),
      } as Record<string, unknown>
    )
  }
  if (trigger == null) {
    return null
  }
  return (
    <button type="button" data-slot="dropdown-menu-trigger" {...buttonProps}>
      {trigger}
    </button>
  )
}

function DropdownMenu({
  open,
  onOpenChange,
  children,
  ...props
}: Omit<React.ComponentProps<typeof MenuTrigger>, "isOpen" | "onOpenChange"> & {
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const triggers: React.ReactNode[] = []
  const rest: React.ReactNode[] = []

  React.Children.forEach(children, (child) => {
    if (React.isValidElement(child) && child.type === DropdownMenuTrigger) {
      triggers.push(
        resolveDropdownMenuTrigger(child.props as DropdownMenuTriggerProps)
      )
    } else if (child != null && child !== false) {
      rest.push(child)
    }
  })

  return (
    <MenuTrigger
      data-slot="dropdown-menu"
      isOpen={open}
      onOpenChange={onOpenChange}
      {...props}
    >
      {triggers}
      {rest}
    </MenuTrigger>
  )
}

function DropdownMenuPortal({ children }: { children?: React.ReactNode }) {
  return <>{children}</>
}

function DropdownMenuTrigger(props: DropdownMenuTriggerProps) {
  return <>{props.children}</>
}

function DropdownMenuContent({
  align = "start",
  alignOffset = 0,
  side = "bottom",
  sideOffset = 4,
  className,
  children,
  ...props
}: React.ComponentProps<typeof Popover> & {
  align?: "start" | "center" | "end"
  alignOffset?: number
  side?: "top" | "bottom" | "left" | "right" | "inline-start" | "inline-end"
  sideOffset?: number
}) {
  return (
    <Popover
      data-slot="dropdown-menu-content"
      placement={toPlacement(side, align)}
      offset={sideOffset}
      crossOffset={alignOffset}
      className={cn(
        "z-50 min-w-32 overflow-hidden rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md outline-none",
        className
      )}
      {...props}
    >
      <Menu className="max-h-60 overflow-auto outline-none">{children}</Menu>
    </Popover>
  )
}

function DropdownMenuGroup({
  className,
  ...props
}: React.ComponentProps<typeof MenuSection>) {
  return (
    <MenuSection
      data-slot="dropdown-menu-group"
      className={cn(className)}
      {...props}
    />
  )
}

function DropdownMenuLabel({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof Header> & { inset?: boolean }) {
  return (
    <Header
      data-slot="dropdown-menu-label"
      data-inset={inset}
      className={cn(
        "px-1.5 py-1 text-xs font-medium text-muted-foreground data-inset:pl-7",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuItem({
  className,
  inset,
  variant = "default",
  disabled,
  onClick,
  ...props
}: Omit<React.ComponentProps<typeof RacMenuItem>, "onAction"> & {
  inset?: boolean
  variant?: "default" | "destructive"
  disabled?: boolean
  onClick?: React.MouseEventHandler<HTMLElement>
}) {
  return (
    <RacMenuItem
      data-slot="dropdown-menu-item"
      data-inset={inset}
      data-variant={variant}
      isDisabled={disabled}
      onPress={
        onClick
          ? (e) => {
              onClick(e as unknown as React.MouseEvent<HTMLElement>)
            }
          : undefined
      }
      className={cn(
        "group/dropdown-menu-item relative flex cursor-default items-center gap-1.5 rounded-md px-1.5 py-1 text-sm outline-none select-none data-[focused]:bg-accent data-[focused]:text-accent-foreground not-data-[variant=destructive]:data-[focused]:**:text-accent-foreground data-inset:pl-7 data-[variant=destructive]:text-destructive data-[variant=destructive]:data-[focused]:bg-destructive/10 data-[variant=destructive]:data-[focused]:text-destructive dark:data-[variant=destructive]:data-[focused]:bg-destructive/20 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 data-[variant=destructive]:*:[svg]:text-destructive",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuSub({ children }: { children?: React.ReactNode }) {
  const items: React.ReactNode[] = []
  React.Children.forEach(children, (child) => {
    if (child != null && child !== false) {
      items.push(child)
    }
  })
  if (items.length >= 2) {
    return (
      <SubmenuTrigger>
        {items[0] as React.ReactElement}
        {items[1] as React.ReactElement}
      </SubmenuTrigger>
    )
  }
  return <>{children}</>
}

function DropdownMenuSubTrigger({
  className,
  inset,
  children,
  ...props
}: React.ComponentProps<typeof RacMenuItem> & { inset?: boolean }) {
  return (
    <RacMenuItem
      data-slot="dropdown-menu-sub-trigger"
      data-inset={inset}
      className={cn(
        "flex cursor-default items-center gap-1.5 rounded-md px-1.5 py-1 text-sm outline-none select-none data-[focused]:bg-accent data-[focused]:text-accent-foreground not-data-[variant=destructive]:data-[focused]:**:text-accent-foreground data-inset:pl-7 data-open:bg-accent data-open:text-accent-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children as React.ReactNode}
      <ChevronRightIcon className="ml-auto" />
    </RacMenuItem>
  )
}

function DropdownMenuSubContent({
  align = "start",
  alignOffset = -3,
  side = "right",
  sideOffset = 0,
  className,
  children,
  ...props
}: React.ComponentProps<typeof DropdownMenuContent>) {
  return (
    <DropdownMenuContent
      data-slot="dropdown-menu-sub-content"
      className={cn(
        "w-auto min-w-[96px] rounded-lg bg-popover p-1 text-popover-foreground shadow-lg ring-1 ring-foreground/10",
        className
      )}
      align={align}
      alignOffset={alignOffset}
      side={side}
      sideOffset={sideOffset}
      {...props}
    >
      {children}
    </DropdownMenuContent>
  )
}

function DropdownMenuCheckboxItem({
  className,
  children,
  checked,
  inset,
  disabled,
  ...props
}: React.ComponentProps<typeof RacMenuItem> & {
  checked?: boolean
  inset?: boolean
  disabled?: boolean
}) {
  return (
    <RacMenuItem
      data-slot="dropdown-menu-checkbox-item"
      data-inset={inset}
      isDisabled={disabled}
      className={cn(
        "relative flex cursor-default items-center gap-1.5 rounded-md py-1 pr-8 pl-1.5 text-sm outline-none select-none data-[focused]:bg-accent data-[focused]:text-accent-foreground data-[focused]:**:text-accent-foreground data-inset:pl-7 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children as React.ReactNode}
      <span
        className="pointer-events-none absolute right-2 flex items-center justify-center"
        data-slot="dropdown-menu-checkbox-item-indicator"
      >
        {checked ? <CheckIcon className="size-4" /> : null}
      </span>
    </RacMenuItem>
  )
}

function DropdownMenuRadioGroup({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dropdown-menu-radio-group"
      role="group"
      className={cn(className)}
      {...props}
    />
  )
}

function DropdownMenuRadioItem({
  className,
  children,
  inset,
  disabled,
  ...props
}: React.ComponentProps<typeof RacMenuItem> & { inset?: boolean; disabled?: boolean }) {
  return (
    <RacMenuItem
      data-slot="dropdown-menu-radio-item"
      data-inset={inset}
      isDisabled={disabled}
      className={cn(
        "relative flex cursor-default items-center gap-1.5 rounded-md py-1 pr-8 pl-1.5 text-sm outline-none select-none data-[focused]:bg-accent data-[focused]:text-accent-foreground data-[focused]:**:text-accent-foreground data-inset:pl-7 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children as React.ReactNode}
      <span
        className="pointer-events-none absolute right-2 flex items-center justify-center"
        data-slot="dropdown-menu-radio-item-indicator"
      >
        <CheckIcon className="size-4 opacity-0 data-selected:opacity-100" />
      </span>
    </RacMenuItem>
  )
}

function DropdownMenuSeparator({
  className,
  ...props
}: React.ComponentProps<typeof Separator>) {
  return (
    <Separator
      data-slot="dropdown-menu-separator"
      className={cn("-mx-1 my-1 h-px bg-border", className)}
      {...props}
    />
  )
}

function DropdownMenuShortcut({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="dropdown-menu-shortcut"
      className={cn(
        "ml-auto text-xs tracking-widest text-muted-foreground group-data-[focused]/dropdown-menu-item:text-accent-foreground",
        className
      )}
      {...props}
    />
  )
}

export {
  DropdownMenu,
  DropdownMenuPortal,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
}
