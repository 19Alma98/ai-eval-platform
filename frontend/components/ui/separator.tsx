"use client"

import type * as React from "react"
import { Separator as RacSeparator } from "react-aria-components"
import { cn } from "cn"

function Separator({
  className,
  orientation = "horizontal",
  ...props
}: React.ComponentProps<typeof RacSeparator>) {
  return (
    <RacSeparator
      data-slot="separator"
      orientation={orientation}
      className={cn(
        "shrink-0 bg-border",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
