FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy application code
COPY . .

# Build the application
RUN npm run build

# Expose port
EXPOSE 5173

# Run the application
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]
