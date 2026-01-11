const puppeteer = require('puppeteer');
const nodemailer = require('nodemailer');

async function approveEdAppUsers() {
  const results = {
    approved: [],
    errors: [],
    timestamp: new Date().toISOString()
  };

  let browser;
  
  try {
    console.log('Launching browser...');
    browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });

    // Login to EdApp
    console.log('Navigating to login page...');
    await page.goto('https://admin.edapp.com/login', { waitUntil: 'networkidle2' });
    
    // Wait for email input and fill it
    await page.waitForSelector('input[name="nameOrEmail"]', { timeout: 10000 });
    await page.type('input[name="nameOrEmail"]', process.env.EDAPP_EMAIL);
    
    // Find and fill password
    await page.type('input[name="password"]', process.env.EDAPP_PASSWORD);
    
    // Click login button
    await page.click('button#btn-login');
    console.log('Logging in...');
    
    // Wait for navigation after login
    await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 30000 });
    
    // Navigate to users page
    console.log('Navigating to users page...');
    await page.goto('https://admin.edapp.com/users?pageSize=25&page=1', { waitUntil: 'networkidle2' });
    
    // Wait a bit for the page to fully load
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    // Look for users without green checkmarks (pending users)
    console.log('Checking for pending users...');
    
    // This will need to be adjusted based on actual HTML structure
    // Strategy: Find all user rows, check if they have approval status
    const pendingUsers = await page.evaluate(() => {
      const users = [];
      // Look for user rows - this selector may need adjustment
      const userRows = document.querySelectorAll('[data-testid="user-row"], tr, .user-item');
      
      userRows.forEach((row, index) => {
        // Check if row has a green checkmark or approved status
        const hasCheckmark = row.querySelector('svg[data-testid="check-icon"], .approved-icon, [class*="check"]');
        const hasApprovedText = row.textContent.toLowerCase().includes('approved');
        
        if (!hasCheckmark && !hasApprovedText) {
          // This might be a pending user
          const nameElement = row.querySelector('[data-testid="user-name"], .user-name, td:first-child');
          const threeDotsButton = row.querySelector('[data-testid="user-menu"], button[aria-label*="menu"], .menu-button');
          
          if (nameElement && threeDotsButton) {
            users.push({
              name: nameElement.textContent.trim(),
              rowIndex: index
            });
          }
        }
      });
      
      return users;
    });
    
    console.log(`Found ${pendingUsers.length} potential pending users`);
    
    if (pendingUsers.length === 0) {
      results.message = 'No pending users found';
    } else {
      // Approve each pending user
      for (const user of pendingUsers) {
        try {
          console.log(`Approving user: ${user.name}`);
          
          // Click the three dots menu for this user
          const menuButtons = await page.$$('[data-testid="user-menu"], button[aria-label*="menu"], .menu-button');
          if (menuButtons[user.rowIndex]) {
            await menuButtons[user.rowIndex].click();
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Look for "Approve" button in the menu
            const approveButton = await page.$('button:has-text("Approve"), [data-testid="approve-user"], button[aria-label*="approve"]');
            
            if (approveButton) {
              await approveButton.click();
              await new Promise(resolve => setTimeout(resolve, 2000));
              
              results.approved.push(user.name);
              console.log(`✓ Approved: ${user.name}`);
            } else {
              results.errors.push(`Could not find approve button for ${user.name}`);
            }
          }
        } catch (error) {
          results.errors.push(`Error approving ${user.name}: ${error.message}`);
          console.error(`Error approving ${user.name}:`, error);
        }
      }
    }
    
  } catch (error) {
    console.error('Error in approval process:', error);
    results.errors.push(`Main process error: ${error.message}`);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
  
  // ONLY send email if users were actually approved
  // Do NOT send email for "no pending users" or if only checking found nothing
  if (results.approved.length > 0) {
    await sendEmailNotification(results);
  } else {
    console.log('No users were approved - skipping email notification');
    // Still log errors to console but don't email about them unless users were approved
    if (results.errors.length > 0) {
      console.log('Errors occurred:', results.errors);
    }
  }
  
  return results;
}

async function sendEmailNotification(results) {
  try {
    // Create transporter
    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: process.env.GMAIL_USER,
        pass: process.env.GMAIL_APP_PASSWORD
      }
    });
    
    // Build email content
    let emailBody = `EdApp User Approval Report\n`;
    emailBody += `Time: ${new Date(results.timestamp).toLocaleString()}\n\n`;
    
    if (results.approved.length > 0) {
      emailBody += `✓ APPROVED USERS (${results.approved.length}):\n`;
      results.approved.forEach(name => {
        emailBody += `  • ${name}\n`;
      });
      emailBody += '\n';
    } else {
      emailBody += `No users were approved.\n\n`;
    }
    
    if (results.errors.length > 0) {
      emailBody += `⚠ ERRORS (${results.errors.length}):\n`;
      results.errors.forEach(error => {
        emailBody += `  • ${error}\n`;
      });
      emailBody += '\n';
    }
    
    if (results.message) {
      emailBody += `${results.message}\n`;
    }
    
    const subject = results.approved.length > 0
      ? `✓ EdApp: ${results.approved.length} user(s) approved`
      : 'EdApp: No pending users';
    
    await transporter.sendMail({
      from: process.env.GMAIL_USER,
      to: process.env.NOTIFICATION_EMAIL,
      subject: subject,
      text: emailBody
    });
    
    console.log('Email notification sent successfully');
  } catch (error) {
    console.error('Error sending email:', error);
  }
}

// Run the function
approveEdAppUsers()
  .then(results => {
    console.log('Process completed:', JSON.stringify(results, null, 2));
    process.exit(0);
  })
  .catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
