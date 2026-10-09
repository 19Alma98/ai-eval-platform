"use client"

import * as React from "react"
import {
  Select as RacSelect,
  SelectValue as RacSelectValue,
  Button,
  Popover,
  ListBox,
  ListBoxItem,
  Header,
} from "react-aria-components"
import { cn } from "cn"
import { ChevronDownIcon, CheckIcon } from "lucide-react"

type SelectRootProps = {
  value?: string
  defaultValue?: string
  onValueChange?: (value: string | null) => void
  disabled?: boolean
  children: React.ReactNode
  className?: string
}

function Select({ value, defaultValue, onValueChange, disabled, children }: SelectRootProps) {
  return (
    <RacSelect
      selectedKey={value || undefined}
      defaultSelectedKey={defaultValue || undefined}
      onSelectionChange={(key) => onValueChange?.(key == null ? null : String(key))}
      isDisabled={disabled}
    >
      {children}
    </RacSelect>
  )
}

function SelectTrigger({
  className,
  size = "default",
  children,
  id,
  ...props
}: React.ComponentProps<typeof Button> & { size?: "sm" | "default"; id?: string }) {
  return (
    <Button
      id={id}
      data-slot="select-trigger"
      data-size={size}
      className={cn(
        "flex w-fit items-center justify-between gap-1.5 rounded-lg border border-input bg-transparent py-2 pr-2 pl-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 data-[size=default]:h-8 data-[size=sm]:h-7",
        className
      )}
      {...props}
    >
      {children as React.ReactNode}
      <ChevronDownIcon className="size-4 text-muted-foreground" />
    </Button>
  )
}

function SelectValue({ className, placeholder, ...props }: React.ComponentProps<typeof RacSelectValue> & { placeholder?: string }) {
  return (
    <RacSelectValue
      data-slot="select-value"
      className={cn("flex flex-1 text-left", className)}
      {...props}
    >
      {({ selectedText }) => selectedText || placeholder || null}
    </RacSelectValue>
  )
}

function SelectContent({ className, children, ...props }: React.ComponentProps<typeof Popover>) {
  return (
    <Popover
      data-slot="select-content"
      className={cn(
        "z-50 min-w-[var(--trigger-width)] overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-md",
        className
      )}
      {...props}
    >
      <ListBox className="max-h-60 overflow-auto p-1 outline-none">{children}</ListBox>
    </Popover>
  )
}

function SelectItem({
  className,
  children,
  value,
  disabled,
  ...props
}: Omit<React.ComponentProps<typeof ListBoxItem>, "id"> & { value: string; disabled?: boolean }) {
  return (
    <ListBoxItem
      id={value}
      textValue={typeof children === "string" ? children : value}
      isDisabled={disabled}
      data-slot="select-item"
      className={cn(
        "relative flex cursor-default items-center gap-2 rounded-md py-1.5 pr-8 pl-2 text-sm outline-none data-[focused]:bg-muted",
        className
      )}
      {...props}
    >
      {({ isSelected }) => (
        <>
          {children}
          {isSelected ? <CheckIcon className="absolute right-2 size-4" /> : null}
        </>
      )}
    </ListBoxItem>
  )
}

function SelectGroup({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="select-group" className={cn("p-1", className)} {...props} />
}

function SelectLabel({ className, ...props }: React.ComponentProps<typeof Header>) {
  return <Header data-slot="select-label" className={cn("px-2 py-1.5 text-xs text-muted-foreground", className)} {...props} />
}

export {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  SelectGroup,
  SelectLabel,
}
