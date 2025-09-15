---
layout: post
title: "Rykerr Medical's Podcast Hosting Strategy"
date: 2025-06-02
tags: [general information, tech stuff]
blurb: how to host a podcast for free (i.e., no cost at all) using github and the internet archive
---

This here write-up is to accompany [the video we’ve posted](https://youtu.be/nNosYLXTu_A) about how our Rykerr Medical Podcast is hosted using free resources out there on the internet.  It is a bit complicated, since there are multiple components and some technical computer stuff, but we think it’s pretty cool and worth sharing.  Plus it lets anyone host a podcast without having to pay a third party to manage the thing.  There’s some stuff here that’s not directly covered in the video and vice versa, [so check the video](https://youtu.be/nNosYLXTu_A) out also.

 A bit of background on this concept to get started.  Also just know that we have zero technical training in this sort of thing, so the explanation here is just how it seems to us while writing this.  A podcast works via a stream of information called an RSS feed.  The RSS feed is directed by and based on a piece of code called an xml file.  Podcasting services can read and share the contents of an RSS feed so that end-users can consume whatever content is presented in that feed.  The idea is that the RSS feed itself is generic and can be shared across different platforms.

 For this whole thing to work we need to make an xml file and then host it onto the internet somehow.  Once that xml file is live in the ether, it is now an RSS feed that we can plug into a podcast host (such as Apple Podcasts or Spotify).  One other consideration, however, is that different hosts have specific rules on how an RSS feed/ xml file needs to be formatted.  While there is a consensus at the macro level, certain hosts have individual requirements.

 So in order to get this thing to work, we need to the following components: audio files and photos hosted on the internet in a way that our RSS feed can access them, a live xml file (also hosted somewhere on the internet), and an xml files that adheres to the rules of both RSS in general and hosts in particular.  And we’re going to make all of this happen on a budget of $0 assuming we already have a computer and some time.  Along the way we’ll point out free options for all the necessary components/ intermediary steps.

 Now there are many ways to host podcasts for free, but the value in managing one’s own RSS feed is that we are no longer dependent on a third-party host and can opt out of both ads and arbitrary rules.  It also allows the creator to port the whole project from one host to another if systems change or if a company goes away without having to rebuild the whole thing. 

 Last thing before jumping in: we stumbled across this system via a lot of trial and error and with the help of ChatGPT.  Computer stuff is not our forte, but we knew what end-goal we wanted and were vaguely familiar with the larger components.  There is probably a lot of room for refinement, but we think it works pretty well as is.  Feel free to let us know if you see any way we can improve the workflow or system.

 Now let’s make it happen.

 First step is to sign up for account on both [archive.org](http://archive.org/) and [github.org](http://github.org/) using whatever email address you want to be affiliated with the thing.  We obviously used our @rykerrmedical.com address since that’s the email used for all the things on this project.  If you need a free option, we’ve used both gmail and proton in the past and either would work just fine.

 Archive.org is the service we use to get our files up onto the internet.  Once the account is created and verified, just log in and there will be an option in the top-right to upload files.  Archive.org can be used to host all different types of files, but we use it for photos (jpeg) and audio files (mp3) for the podcast thing.  We upload the content for each episode in a single bundle, i.e. the photo and the audio file in the same page - this allows us to use the resulting page on archive.org as the podcast episode webpage in our RSS feed or xml file (more on that later).  If that isn’t clear, refer to the video to see how it works.

 If you want your podcast to make its way onto all the various podcast feeds, it makes the most sense to follow the rules set forth by Apple Podcasts, as they are the most specific.  One rule they have is that photos need to be square and at least 1400 x 1400 pixels and no larger than 3000 x 3000.  We can do this either on an iPhone (cropping in the photos app, compressing to a given size using an app called Compress) or on a computer (Mac or Windows) using open-source software called GIMP.  There are many ways to resize and crop photos, but that’s how we get it done.

 When we want to play around with images or combine photos, we aren’t committed to one specific piece of software and use any combination of the following (which, of course, are all available for free): Adobe Express (on iPhone), GIMP (on Mac), PowerPoint (on Mac) and Sketchbook (on iPad).  We use these things for all kinds of illustrations, just to be clear, not just the podcast cover photos.

 As for the audio file, we do most of recording, editing, and mixing using another open-source program called Audacity.  We have also used Spotify for Podcasters (back when it was [Anchor.fm](http://anchor.fm/) and Zoom.   Unfortunately the call recording feature that defined Anchor.fm went away when Spotify took over, so that’s sad.  And Zoom is kind of lame and not free, but allows us to capture video…. There is, however, a free option called Jitsi that we hope to trial soon.  And lastly there is an iPhone app called “voice recorder” that is very similar to the default “voice memo” app on iPhone, but allows you to save and send recordings as mp3 files which saves one step of needing to convert the file.

 So that’s how we get the audio files and photos sorted and prepped and uploaded onto the internet.  There are many free options for hosting on the internet (such as OneDrive and GoogleDrive), but archive.org has a few unique features that make it suitable for the podcast thing.  First is that each episode of the podcast ends up with its own page on archive.org and this (hopefully and in alignment with the mission of the archive.org non-profit) is a way to preserve content for posterity’s sake.  Second and most important is that archive.org hosts files with a URL that prompts a direct download of the file it directs to and supports something called “head requests” which allows the end-host (i.e., Apple Podcasts or Spotify) to verify the thing.  That’s the extent of our understanding and we learned it from ChatGPT when hosting files other ways didn’t work…. That said, there may be other ways to host the files, but we think archive.org is rad and that’s what we’ve opted to stick with.

 Alrighty, so now we have made the audio files and built our graphics and have them saved on archive.org (for free and forever).  Next step is to build the RSS feed itself over at github.org.  As a quick aside: github isn’t necessarily designed for this, rather it serves as a way for folks to host code and collaborate with other developers.  That said, there are lots of what we’d call off-label uses of github, and this is simply another one of those.  Heads up though: this part has some specific instructions and can be a little confusing.  It took us many tries and a number of long talks with ChatGPT to figure this all out.

 We’ll set the thing up in a web browser, but once that’s done you can do subsequent steps (i.e., publish episodes and modify the xml file/ RSS feed) from any device.  Log into your github account.  Create a repository and label it “landing.”  Create a “readme” file when github prompts you to do so, feel free to add descriptive text in here as you see fit, then “commit changes.”  After that, click on “landing” at the top, then on the “+” symbol to create a new file, label it as “feed.xml.”  And then do the same thing over to create another file named “index.html.”  To be 100% honest, it’s not totally clear if the readme part is necessary, but since github prompts you to do it and it’s simple, seemed like the right decision.  The other two parts, however, are both necessary – we absolutely do need an index.html and feed.xml for this to work.

 Now that our repository and the pages are done, we need to build the code of the xml file which is the technical piece of our RSS feed.  In either a web browser or on a device (such as an iPhone with the github app) got to the home screen, click “repositories” on the left, click “landing,” click “code,” select “feed.xml” and edit by clicking the three dots (in the app) or the pencil (web browser) in the top-right.  Now we can type away to our heart’s content to edit our xml file.

 To get started, feel free to copy the format of the xml file for the Rykerr Medical Podcast.  Here’s how it looks with just the first two episodes:

    <?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
      <channel>
        <title>The Rykerr Medical Podcast</title>
        <link>https://rykerrmedical.github.io/landing/</link>
        <description>Rykerr Medical LLC is a platform for education focused on emergency, transport, and critical care medicine.</description>
        <language>en-us</language>
        <itunes:category text="Education"/>
        <itunes:image href="https://archive.org/download/submark1/submark1.jpeg"/>
        <itunes:explicit>false</itunes:explicit>
        <itunes:author>Rykerr Medical</itunes:author>
        <itunes:owner>
          <itunes:name>Rykerr Medical LLC</itunes:name>
          <itunes:email>ryan@rykerrmedical.com</itunes:email>
        </itunes:owner>

        <item>
          <title>Scripts Discussion with Richard</title>
          <description><![CDATA[
        In this episode we discuss the idea of creating scripts for learning protocols and refining procedures with Richard Templeman, a flight paramedic in Nevada.  We talk about the development of the idea, outline how we've used it personally, and provide examples of how you can do the same in your own clinical practice.  Let us know what you think and reach out with any questions.<br />
            <br />
            episode webpage: https://archive.org/details/scripts-discussion-with-richard_202502<br />
            <br />
            www.rykerrmedical.com to see what else is going on with the project
          ]]></description>
          <enclosure url="https://archive.org/download/scripts-discussion-with-richard_202502/Scripts_Discussion_with_Richard.mp3" type="audio/mpeg" length="31155456"/>
            <pubDate>Thu, 21 Jun 2021 12:00:00 +0000</pubDate>
          <itunes:author>Rykerr Medical</itunes:author>
          <itunes:image href="https://archive.org/download/scripts-discussion-with-richard_202502/Scripts_Discussion_with_Richard.jpg"/>
          <link>https://archive.org/details/scripts-discussion-with-richard_202502</link>
          <guid isPermaLink="true">https://archive.org/details/scripts-discussion-with-richard_202502</guid>
        </item>

        <item>
          <title>What is Up at Rykerr Medical?</title>
          <description><![CDATA[
            This episode is a short introduction to both the podcast and Rykerr Medical in general. Take a listen and let us know what you think!<br />
            <br />
            episode webpage: https://archive.org/details/what-is-up-at-rykerr-medical_202502<br />
            <br />
            www.rykerrmedical.com to see what else is going on with the project
          ]]></description>
          <enclosure url="https://archive.org/download/what-is-up-at-rykerr-medical_202502/What_is_Up_at_Rykerr_Medical.mp3" type="audio/mpeg" length="14586624"/>
          <pubDate>Wed, 2 Jun 2021 12:00:00 +0000</pubDate>
          <itunes:author>Rykerr Medical</itunes:author>
          <itunes:image href="https://archive.org/download/what-is-up-at-rykerr-medical_202502/What_is_Up_at_Rykerr_Medical.JPG"/>
          <link>https://archive.org/details/what-is-up-at-rykerr-medical_202502</link>
          <guid isPermaLink="true">https://archive.org/details/what-is-up-at-rykerr-medical_202502</guid>
        </item>
      </channel>
    </rss>

 And for future reference if this gets outdated or formatting requirements change or we figure out how to do it better, the URL is: [https://rykerrmedical.github.io/landing/feed.xml](https://rykerrmedical.github.io/landing/feed.xml).  Just paste it into your web browser and you can see the current state of the thing.

 Now that’s a bit complicated and includes lots of things that may be unfamiliar, but let’s create a hypothetical podcast and we’ll edit the xml file to reflect our new project.  We’ll name the hypothetical podcast “The Hypothetical Podcast” and we, hypothetically of course, create our github account with the username HypotheticalCast.

 The first bit of the xml file is the general information and the following sections are for each episode.  If you’re curious about which each of the specific line items mean, please refer to both the video we made and our dear friend ChatGPT who seems to know a lot more about the technical specifics than we do.  There are also many tutorials online that explain what each line item means.  But let’s plug in pretend information into our file to create our hypothetical RSS feed: 

    <?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
      <channel>
        <title>The Hypothetical Podcast</title>
        <link>https://hypotheticalcast.github.io/landing/</link>
        <description>The Hypothetical Podcast isn’t even real!</description>
        <language>en-us</language>
        <itunes:category text="Education"/>
        <itunes:image href="https://archive.org/hypotheticalcastgraphic.jpeg"/>
        <itunes:explicit>false</itunes:explicit>
        <itunes:author>A Hypothetical Human</itunes:author>
        <itunes:owner>
          <itunes:name>The Hypothetical Podcast</itunes:name>
          <itunes:email>HypotheticalCast@gmail.com</itunes:email>
        </itunes:owner>
    
        <item>
          <title>What is Up at The Hypothetical Podcast</title>
          <description><![CDATA[
            This episode is a short introduction to The Hypothetical Podcast. Take a listen and let us know what you think!<br />
            <br />
            episode webpage: https://archive.org/details/hypothetical-podcast-1<br />
            <br />
            www.hypotheticalcast.com to see what else is going on with the project
          ]]></description>
          <enclosure url="https://archive.org/download/what-is-up-at-hypothetical-podcast/What_is_Up_at_Hypothetical_Podcast. mp3" type="audio/mpeg" length="14586624"/>
          <pubDate>Sat, 8 Mar 2025 12:00:00 +0000</pubDate>
          <itunes:author> A Hypothetical Human </itunes:author>
            <itunes:image href="https://archive.org/download/what-is-up-at-hypothetical-podcast/What_is_Up_at_Hypothetical_Podcast.JPG"/>
          <link>https://archive.org/details/what-is-up-at-hypothetical-podcast</link>
          <guid isPermaLink="true"> https://archive.org/details/what-is-up-at-hypothetical-podcast</guid>
        </item>
      </channel>
    </rss>

 So we just copy that into the xml file in github and “commit changes” to make it live.  Next time we have a new episode, just copy everything from “<item>” to “</item>” and insert the specifics for the new episode of the podcast. 

 Note that not all of those fields/ lines are necessary.  We could for sure simplify the xml file and RSS feed, this is just an example of how we have set ours up.   

Next step is to verify the xml file to make sure it meets all the standard requirements.  There are many websites and tools to do this, but the two we use are Cast Feed Validator and W3C.  We just copy and paste the URL of our feed (https://hypotheticalcast.github.io/landing/feed.xml) into the tool and they each provide a report with any errors as well as suggestions to fix them.  In learning this process, we came across many, many errors and not all of them were that simple or straightforward to fix.  We leaned heavily on ChatGPT to troubleshoot specifics when the guidance from these validator tools wasn’t super clear.

 One specific example that we show in the video and may not be easy to parse out from the reports provided by these RSS feed validators is the piece labeled “length” in the line that includes the URL to the audio file for the podcast:

    <enclosure url="https://archive.org/download/what-is-up-at-hypothetical-podcast/What_is_Up_at_Hypothetical_Podcast. mp3" type="audio/mpeg" length="14586624"/>

 This random bunch of numbers is actually the number of bytes in the mp3 file.  If you get an example xml file for podcasts off the internet, the placeholder here is often 12345.  But if we leave the length value as 12345 our podcast, in theory, could get cut off early when playing.  That said, this is one of those grey areas in this whole process – we initially left it alone as 12345 and it worked just fine.  We eventually worked out what the thing was and updated our xml file, but this may not be a necessary step.  And to get this number, we need to know that 1 MB = 1,048,576 bytes.

 So we have an xml file hosted via github to the interwebs.  We also have files, the actual podcast content, hosted in a way on archive.org that allows the RSS feed to access them.  And we validated our RSS feed and think we have it more or less ready to publish to the strangers of the world.

 Last step in all of this is to get our RSS feed out there into the wild.  This requires putting our RSS feed into some sort of system that normal folks use access podcasts.  The two most common are Apple Podcasts and Spotify.  Regardless of which one we use, we can still publish our podcast to both (and also other, less common hosts), so it doesn’t really matter.  We’ve used both and they are both more or less the same.  So go on over to either one, make an account, and use the custom RSS feed we created (instead of the one they would create).  Details for that are omitted here since both Spotify and Apple have instructions and how-to docs on their websites.  The podcast will then be live on the chosen platform and we can also choose to “distribute” to other hosts.

 And that’s it.  We now have a podcast hosted on both Spotify and Apple Podcast, just like all of the pros, but we maintain ownership of our RSS feed, have the content archived on the internet (hopefully) forever, and can freely decide where we want to host the thing.  Happy podcasting!
