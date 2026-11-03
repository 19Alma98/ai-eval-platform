"use client"

import * as React from "react"
import {
  Dialog as RacDialog,
  DialogTrigger as RacDialogTrigger,
  OverlayTriggerStateContext,
  Modal,
  ModalOverlay,
  Heading,
  Text,
} from "react-aria-components"
import { cn } from "cn"
import { Button } from "@/components/ui/button"
import { XIcon } from "lucide-react"

type DialogTriggerProps = React.ComponentProps<"button"> & {
  render?: React.ReactElement
  children?: React.ReactNode
}

function resolveDialogTrigger(props: DialogTriggerProps) {
  const { render, children, ...buttonProps } = props
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
        "data-slot": "dialog-trigger",
        className: cn(triggerProps.className),
      } as Record<string, unknown>
    )
  }
  if (trigger == null) {
    return null
  }
  return (
    <button type="button" data-slot="dialog-trigger" {...buttonProps}>
      {trigger}
    </button>
  )
}

function Dialog({
  open,
  onOpenChange,
  children,
  ...props
}: {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children: React.ReactNode
} & Omit<
  React.ComponentProps<typeof RacDialogTrigger>,
  "children" | "isOpen" | "onOpenChange"
>) {
  const triggers: React.ReactNode[] = []
  const rest: React.ReactNode[] = []

  // Children are collected into arrays, so each needs a key of its own.
  React.Children.forEach(children, (child) => {
    if (React.isValidElement(child) && child.type === DialogTrigger) {
      const trigger = resolveDialogTrigger(child.props as DialogTriggerProps)
      triggers.push(
        React.isValidElement(trigger)
          ? React.cloneElement(trigger, { key: `trigger-${triggers.length}` })
          : trigger
      )
    } else if (child != null && child !== false) {
      rest.push(
        React.isValidElement(child) && child.key == null
          ? React.cloneElement(child, { key: `content-${rest.length}` })
          : child
      )
    }
  })

  // No trigger (opened from a menu item or elsewhere): RAC's DialogTrigger needs a
  // pressable child, so hand the modal its open state directly instead.
  if (triggers.length === 0) {
    const isOpen = open ?? false
    const setOpen = (next: boolean) => onOpenChange?.(next)
    return (
      <OverlayTriggerStateContext.Provider
        value={{
          isOpen,
          setOpen,
          open: () => setOpen(true),
          close: () => setOpen(false),
          toggle: () => setOpen(!isOpen),
          point: null,
          setPoint: () => {},
        }}
      >
        {rest}
      </OverlayTriggerStateContext.Provider>
    )
  }

  return (
    <RacDialogTrigger
      data-slot="dialog"
      isOpen={open}
      onOpenChange={onOpenChange}
      {...props}
    >
      {triggers}
      {rest}
    </RacDialogTrigger>
  )
}

/** Marker + props holder; `Dialog` resolves `render` / children into the RAC trigger. */
function DialogTrigger(props: DialogTriggerProps) {
  void props
  return null
}

function DialogPortal({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof ModalOverlay>) {
  return (
    <ModalOverlay
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/20 entering:animate-in entering:fade-in-0 exiting:animate-out exiting:fade-out-0",
        className
      )}
      {...props}
    />
  )
}

/**
 * A full-height side panel anchored to the right edge: square, ruled header and footer,
 * scrolls on its own. Callers set its width with `sm:max-w-*` (default `sm:max-w-md`).
 */
function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: Omit<React.ComponentProps<typeof RacDialog>, "children"> & {
  showCloseButton?: boolean
  className?: string
  children?: React.ReactNode
}) {
  return (
    <DialogOverlay>
      <Modal
        className="fixed inset-y-0 right-0 z-50 flex entering:animate-in entering:slide-in-from-right exiting:animate-out exiting:slide-out-to-right"
      >
        <RacDialog
          data-slot="dialog-content"
          className={cn(
            "relative flex h-full w-screen flex-col border-l border-border bg-background text-sm text-foreground outline-none sm:max-w-md",
            className
          )}
          {...props}
        >
          {/* Scrolls inside the panel so the close button and the panel edge stay put. */}
          <div
            data-slot="dialog-body"
            className={cn(
              "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5",
              // Forms wrapping header, body and footer fill the panel so the footer sits at the bottom.
              "[&>form]:flex [&>form]:flex-1 [&>form]:flex-col",
              // Panels without a footer still get bottom breathing room.
              "[&:not(:has([data-slot=dialog-footer]))]:pb-5"
            )}
          >
            {children}
          </div>
          {showCloseButton ? (
            <Button
              slot="close"
              variant="ghost"
              size="icon-sm"
              className="absolute top-4 right-4 z-20"
              aria-label="Close"
            >
              <XIcon />
            </Button>
          ) : null}
        </RacDialog>
      </Modal>
    </DialogOverlay>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn(
        "sticky top-0 z-10 -mx-5 flex flex-col gap-1.5 border-b border-border bg-background px-5 pt-5 pb-4 pr-14",
        className
      )}
      {...props}
    />
  )
}

function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean
}) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "sticky bottom-0 z-10 -mx-5 mt-auto flex flex-col-reverse gap-2 border-t border-border bg-background px-5 py-4 sm:flex-row sm:justify-end",
        className
      )}
      {...props}
    >
      {children}
      {showCloseButton ? (
        <Button slot="close" variant="outline" data-slot="dialog-close">
          Close
        </Button>
      ) : null}
    </div>
  )
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof Heading>) {
  return (
    <Heading
      slot="title"
      data-slot="dialog-title"
      className={cn("font-serif text-lg font-medium tracking-tight", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof Text>) {
  return (
    <Text
      slot="description"
      data-slot="dialog-description"
      className={cn(
        "text-sm text-muted-foreground *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground",
        className
      )}
      {...props}
    />
  )
}

function DialogClose(props: React.ComponentProps<typeof Button>) {
  return <Button slot="close" data-slot="dialog-close" {...props} />
}

export {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  DialogClose,
  DialogOverlay,
  DialogPortal,
}
