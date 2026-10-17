# Reproducible Android build environment for the JARVIS APK (no Android Studio needed).
FROM eclipse-temurin:17.0.20_8-jdk-noble

ENV ANDROID_HOME=/opt/android-sdk \
    GRADLE_USER_HOME=/cache/gradle
ENV PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:/opt/gradle/bin

RUN apt-get update && apt-get install -y --no-install-recommends unzip curl && rm -rf /var/lib/apt/lists/*

# Android command-line tools 12.0 + SDK 35
RUN mkdir -p $ANDROID_HOME/cmdline-tools \
 && curl -fsSL -o /tmp/clt.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && unzip -q /tmp/clt.zip -d $ANDROID_HOME/cmdline-tools && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
 && rm /tmp/clt.zip \
 && yes | sdkmanager --licenses >/dev/null \
 && sdkmanager --install "platforms;android-35" "build-tools;35.0.0" "platform-tools" >/dev/null

# Gradle (only used to bootstrap the project's wrapper)
RUN curl -fsSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-8.11.1-bin.zip \
 && unzip -q /tmp/gradle.zip -d /opt && mv /opt/gradle-8.11.1 /opt/gradle && rm /tmp/gradle.zip

WORKDIR /src
