"use client"

import * as React from "react"
import {
  Dialog as RacDialog,
  DialogTrigger as RacDialogTrigger,
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

  React.Children.forEach(children, (child) => {
    if (React.isValidElement(child) && child.type === DialogTrigger) {
      triggers.push(resolveDialogTrigger(child.props as DialogTriggerProps))
    } else if (child != null && child !== false) {
      rest.push(child)
    }
  })

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
        "fixed inset-0 z-50 bg-black/10 entering:animate-in entering:fade-in-0 exiting:animate-out exiting:fade-out-0",
        className
      )}
      {...props}
    />
  )
}

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
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 sm:max-w-sm"
        )}
      >
        <RacDialog
          data-slot="dialog-content"
          className={cn(
            "relative grid gap-4 rounded-xl bg-popover p-4 text-sm text-popover-foreground ring-1 ring-foreground/10 outline-none",
            className
          )}
          {...props}
        >
          {children}
          {showCloseButton ? (
            <Button
              slot="close"
              variant="ghost"
              size="icon-sm"
              className="absolute top-2 right-2"
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
      className={cn("flex flex-col gap-2", className)}
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
        "-mx-4 -mb-4 flex flex-col-reverse gap-2 rounded-b-xl border-t bg-muted/50 p-4 sm:flex-row sm:justify-end",
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
      className={cn("text-base font-semibold", className)}
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
