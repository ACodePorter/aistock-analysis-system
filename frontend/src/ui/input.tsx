import React from 'react';

interface InputProps {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  onKeyPress?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  className?: string;
  type?: string;
}

export function Input({ 
  value, 
  onChange, 
  placeholder = '', 
  onKeyPress,
  className = '',
  type = 'text'
}: InputProps) {
  return (
    <input
      type={type}
      value={value}
      onChange={onChange}
      onKeyPress={onKeyPress}
      placeholder={placeholder}
      className={`dark-input ${className}`}
    />
  );
}
