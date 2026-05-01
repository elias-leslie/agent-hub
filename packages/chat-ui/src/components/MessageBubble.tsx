import { useState } from "react";
import type { ChatMessage } from "../types/chat";
import { cn } from "../lib/utils";
import { ToolExecutionDisplay } from "./ToolExecutionDisplay";
import { ProviderBadge } from "./ProviderBadge";
import { ThinkingBlock } from "./ThinkingBlock";
import { MessageActions } from "./MessageActions";
import { EditableContent } from "./EditableContent";
import { MessageContent } from "./MessageContent";
import { getProviderBubbleStyle } from "./message-bubble-utils";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming: boolean;
  onEdit?: (messageId: string, newContent: string) => void;
  onRegenerate?: (messageId: string) => void;
  onContinue?: (messageId: string) => void;
  onContinueAs?: (model: string, prompt: string) => void;
  canEdit: boolean;
  canRegenerate: boolean;
  canContinue?: boolean;
}

export function MessageBubble({
  message,
  isStreaming,
  onEdit,
  onRegenerate,
  onContinue,
  onContinueAs,
  canEdit,
  canRegenerate,
  canContinue = false,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const [isHovered, setIsHovered] = useState(false);

  const handleSaveEdit = () => {
    if (onEdit && editContent.trim() !== message.content) {
      onEdit(message.id, editContent.trim());
    }
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setEditContent(message.content);
    setIsEditing(false);
  };

  const handleStartEdit = () => {
    setEditContent(message.content);
    setIsEditing(true);
  };

  return (
    <div
      id={`msg-${message.id}`}
      className={cn("flex group", isUser ? "justify-end" : "justify-start")}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className={cn("flex items-start gap-2", isUser ? "max-w-[85%]" : "w-full max-w-[72rem]")}>
        {/* Action buttons for assistant (left side) */}
        {!isUser && (
          <MessageActions
            isUser={false}
            isStreaming={isStreaming}
            isEditing={isEditing}
            isHovered={isHovered}
            canEdit={false}
            canRegenerate={canRegenerate}
            canContinue={canContinue}
            onRegenerate={onRegenerate ? () => onRegenerate(message.id) : undefined}
            onContinue={onContinue ? () => onContinue(message.id) : undefined}
          />
        )}

        {/* Message bubble */}
        <div
          className={cn(
            "relative rounded-md",
            isUser ? "px-4 py-2" : "px-5 py-4",
            getProviderBubbleStyle(message, isUser),
            message.cancelled && "border-2 border-yellow-500"
          )}
        >
          {/* Model/Agent badge */}
          {!isUser && <ProviderBadge message={message} />}

          {/* Extended thinking block */}
          {!isUser && message.thinking && (
            <ThinkingBlock
              thinking={message.thinking}
              thinkingTokens={message.thinkingTokens}
              isStreaming={isStreaming}
              hasContent={!!message.content}
            />
          )}

          {/* Tool executions display */}
          {!isUser && message.toolExecutions && message.toolExecutions.length > 0 && (
            <ToolExecutionDisplay tools={message.toolExecutions} />
          )}

          {/* Content - editable or readonly */}
          {isEditing ? (
            <EditableContent
              isUser={isUser}
              editContent={editContent}
              onContentChange={setEditContent}
              onSave={handleSaveEdit}
              onCancel={handleCancelEdit}
            />
          ) : (
            <MessageContent
              message={message}
              isUser={isUser}
              isStreaming={isStreaming}
              onContinueAs={onContinueAs}
            />
          )}
        </div>

        {/* Action buttons for user (right side) */}
        {isUser && (
          <MessageActions
            isUser={true}
            isStreaming={isStreaming}
            isEditing={isEditing}
            isHovered={isHovered}
            canEdit={canEdit}
            canRegenerate={false}
            onEdit={onEdit ? handleStartEdit : undefined}
          />
        )}
      </div>
    </div>
  );
}
